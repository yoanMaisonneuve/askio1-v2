"""
pybullet_sim.py — Simulation physique PyBullet (Phase 10b)
===========================================================
Remplace Gazebo pour la simulation. Avantages :
  - pip install pybullet — zéro dépendance ROS2
  - Fonctionne en headless (sans écran) — parfait pour CI et sandbox
  - Charge directement les URDF générés par urdf_generator.py
  - Physique réelle (contacts, gravité, inertie)
  - 10-100× plus rapide que temps réel en mode DIRECT

Workflow :
  1. Charge URDF du proto dans PyBullet (mode DIRECT = headless)
  2. Applique les angles CPG joint par joint à chaque step
  3. Récupère position + orientation du corps (vraie physique)
  4. Calcule métriques réelles (distance, stabilité, énergie)
  5. Sauvegarde résultats dans MEA + journal

Usage :
  python -m askio1.simulation.pybullet_sim --proto proto1_tripod --dur 10.0
  python -m askio1.simulation.pybullet_sim --proto proto2_quad --gait trot
"""

import logging
import math
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SIM_DIR  = Path(__file__).parent
PROJ_DIR = SIM_DIR.parent.parent


@dataclass
class SimResult:
    proto: str
    gait: str
    duration_s: float
    distance_m: float
    forward_speed_ms: float
    stability_score: float
    energy_J: float
    falls: int
    global_score: float
    n_steps: int
    real_time_factor: float  # combien de fois plus vite que temps réel

    def summary(self) -> str:
        return (
            f"[{self.proto}/{self.gait}] "
            f"dist={self.distance_m:.3f}m  "
            f"speed={self.forward_speed_ms:.3f}m/s  "
            f"stability={self.stability_score:.2f}  "
            f"energy={self.energy_J:.2f}J  "
            f"falls={self.falls}  "
            f"score={self.global_score:.3f}  "
            f"RTF={self.real_time_factor:.1f}x"
        )


class PyBulletSim:
    """
    Simulation PyBullet en mode DIRECT (headless).
    Connecte le CPGController aux joints du robot en temps réel simulé.
    """

    GRAVITY   = -9.81
    TIMESTEP  = 0.002   # 500 Hz physique interne (stabilité contacts)
    CPG_DT    = 0.01    # 100 Hz CPG (1 step CPG tous les 5 steps physique)
    PHYS_PER_CPG = 5    # CPG_DT / TIMESTEP

    def __init__(self, urdf_path: str, proto: str = "proto1_tripod",
                 gait: str = "tripod_wave", freq: float = 1.0, gui: bool = False):
        self.urdf_path = Path(urdf_path)
        self.proto     = proto
        self.gait      = gait
        self.freq      = freq
        self.gui       = gui
        self._pb       = None
        self._robot_id = None
        self._joint_map: dict = {}  # joint_name → joint_index

    def _connect(self):
        import pybullet as pb
        import pybullet_data
        self._pb = pb

        mode = pb.GUI if self.gui else pb.DIRECT
        self._client = pb.connect(mode)

        pb.setAdditionalSearchPath(pybullet_data.getDataPath())
        pb.setGravity(0, 0, self.GRAVITY, physicsClientId=self._client)
        pb.setTimeStep(self.TIMESTEP,     physicsClientId=self._client)
        pb.setRealTimeSimulation(0,        physicsClientId=self._client)

        # Sol
        pb.loadURDF("plane.urdf", physicsClientId=self._client)

        # Robot
        if not self.urdf_path.exists():
            raise FileNotFoundError(f"URDF introuvable : {self.urdf_path}")

        self._robot_id = pb.loadURDF(
            str(self.urdf_path),
            basePosition=[0, 0, 0.20],
            baseOrientation=pb.getQuaternionFromEuler([0, 0, 0]),
            flags=pb.URDF_USE_INERTIA_FROM_FILE,
            physicsClientId=self._client,
        )
        logger.info(f"[PyBullet] robot chargé — {pb.getNumJoints(self._robot_id, physicsClientId=self._client)} joints")

        # Mappe les noms de joints → indices
        n = pb.getNumJoints(self._robot_id, physicsClientId=self._client)
        for i in range(n):
            info = pb.getJointInfo(self._robot_id, i, physicsClientId=self._client)
            name = info[1].decode("utf-8")
            if info[2] == pb.JOINT_REVOLUTE:
                self._joint_map[name] = i

        logger.info(f"[PyBullet] joints revolute : {list(self._joint_map.keys())}")

    def _disconnect(self):
        if self._pb and self._client is not None:
            self._pb.disconnect(physicsClientId=self._client)

    def run(self, duration: float = 10.0) -> SimResult:
        """Lance la simulation et retourne les métriques."""
        sys.path.insert(0, str(PROJ_DIR))
        from askio1.simulation.cpg_controller import CPGController

        self._connect()
        pb = self._pb

        cpg = CPGController(
            n_legs=3 if "tripod" in self.proto else 4,
            gait=self.gait,
            freq=self.freq,
            dt=self.CPG_DT,
        )

        total_physics_steps = int(duration / self.TIMESTEP)
        pos_history   = []
        orient_history= []
        energy_sum    = 0.0
        falls         = 0
        was_fallen    = False
        t_wall_start  = time.perf_counter()

        angles = cpg.step()  # premier step CPG

        for step in range(total_physics_steps):

            # Mise à jour CPG tous les PHYS_PER_CPG steps physique
            if step % self.PHYS_PER_CPG == 0:
                angles = cpg.step()

                # Applique les angles aux joints correspondants
                for joint_name, angle in angles.items():
                    if joint_name in self._joint_map:
                        idx = self._joint_map[joint_name]
                        pb.setJointMotorControl2(
                            self._robot_id, idx,
                            pb.POSITION_CONTROL,
                            targetPosition=angle,
                            force=5.0,
                            maxVelocity=3.0,
                            physicsClientId=self._client,
                        )

            # Step physique
            pb.stepSimulation(physicsClientId=self._client)

            # Mesures tous les 50 Hz (10 steps)
            if step % 10 == 0:
                pos, quat = pb.getBasePositionAndOrientation(
                    self._robot_id, physicsClientId=self._client)
                roll, pitch, yaw = pb.getEulerFromQuaternion(quat)
                pos_history.append(pos)
                orient_history.append((roll, pitch, yaw))

                # Énergie : somme des couples × vitesses
                for i in self._joint_map.values():
                    state = pb.getJointState(self._robot_id, i,
                                              physicsClientId=self._client)
                    vel, torque = state[1], state[3]
                    energy_sum += abs(torque * vel) * self.TIMESTEP * 10

                # Détection chute (corps trop bas)
                if pos[2] < 0.04:
                    if not was_fallen:
                        falls += 1
                        was_fallen = True
                else:
                    was_fallen = False

        t_wall = time.perf_counter() - t_wall_start
        rtf    = duration / t_wall if t_wall > 0 else 1.0

        self._disconnect()

        # ── Métriques ─────────────────────────────────────────────────────────
        if len(pos_history) < 2:
            dist, speed, stability = 0.0, 0.0, 1.0
        else:
            p0, p1 = pos_history[0], pos_history[-1]
            dist   = math.sqrt((p1[0]-p0[0])**2 + (p1[1]-p0[1])**2)
            speed  = dist / duration

            rolls  = [o[0] for o in orient_history]
            pitchs = [o[1] for o in orient_history]
            var    = (max(rolls)-min(rolls) + max(pitchs)-min(pitchs)) / 2
            stability = max(0.0, 1.0 - var / (math.pi/4))

        speed_norm = min(speed / 0.5, 1.0)
        energy_norm= max(0.0, 1.0 - energy_sum / 20.0)
        score = (0.40*speed_norm + 0.40*stability + 0.10*energy_norm - 0.30*falls)
        score = max(0.0, round(score, 4))

        result = SimResult(
            proto=self.proto, gait=self.gait,
            duration_s=duration,
            distance_m=round(dist, 4),
            forward_speed_ms=round(speed, 4),
            stability_score=round(stability, 4),
            energy_J=round(energy_sum, 4),
            falls=falls,
            global_score=score,
            n_steps=total_physics_steps,
            real_time_factor=round(rtf, 1),
        )

        logger.info(f"[PyBullet] {result.summary()}")
        return result

    @staticmethod
    def run_all_protos(duration: float = 10.0) -> list:
        """Lance PROTO-1 et PROTO-2 et retourne les résultats comparatifs."""
        results = []
        configs = [
            ("proto1_tripod", "tripod_wave", 3, 1.0),
            ("proto1_tripod", "tripod_static", 3, 0.8),
            ("proto2_quad",   "trot",          4, 1.0),
            ("proto2_quad",   "walk",          4, 0.6),
        ]
        for proto, gait, _, freq in configs:
            urdf = PROJ_DIR / f"robot/{proto}/urdf/{proto}.urdf"
            if not urdf.exists():
                logger.warning(f"[PyBullet] URDF manquant : {urdf}")
                continue
            sim = PyBulletSim(str(urdf), proto=proto, gait=gait, freq=freq)
            try:
                r = sim.run(duration)
                results.append(r)
                print(f"  {r.summary()}")
            except Exception as e:
                logger.error(f"[PyBullet] erreur {proto}/{gait}: {e}")
        return results


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, json, dataclasses
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s — %(message)s")

    parser = argparse.ArgumentParser(description="Simulation PyBullet — Askio1 v2")
    parser.add_argument("--proto", default="proto1_tripod",
                        choices=["proto1_tripod", "proto2_quad"])
    parser.add_argument("--gait",  default="tripod_wave")
    parser.add_argument("--freq",  type=float, default=1.0)
    parser.add_argument("--dur",   type=float, default=10.0)
    parser.add_argument("--gui",   action="store_true", help="Affiche la GUI PyBullet")
    parser.add_argument("--all",   action="store_true", help="Lance tous les protos")
    parser.add_argument("--out",   default=None)
    args = parser.parse_args()

    if args.all:
        print("\n🤖 Benchmark tous prototypes :")
        results = PyBulletSim.run_all_protos(args.dur)
        best = max(results, key=lambda r: r.global_score) if results else None
        if best:
            print(f"\n🏆 Meilleur : {best.proto}/{best.gait} — score {best.global_score}")
    else:
        urdf = PROJ_DIR / f"robot/{args.proto}/urdf/{args.proto}.urdf"
        sim  = PyBulletSim(str(urdf), proto=args.proto, gait=args.gait,
                           freq=args.freq, gui=args.gui)
        print(f"\n🤖 Simulation {args.proto} / {args.gait} / {args.dur}s ...")
        result = sim.run(args.dur)
        print(f"\n{result.summary()}")

        out = Path(args.out) if args.out else \
              Path(f"data/artifacts/report/sim_{args.proto}_{args.gait}.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(dataclasses.asdict(result), indent=2), encoding="utf-8")
        print(f"✓ Sauvegardé : {out}")
