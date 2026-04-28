"""
cpg_tuner.py — Tuning automatique des parametres CPG (Phase 11)
================================================================
Ajuste les parametres du CPGController par recherche iterative
pour maximiser le score de simulation PyBullet.

Algorithme : Random Search + Hill Climbing
  1. Echantillonne N configurations aleatoires
  2. Prend les K meilleures (score PyBullet)
  3. Perturbe et affine autour des meilleures
  4. Repete jusqu'a convergence ou max_iterations

Parametres CPG tunables :
  - freq          : frequence de pas (0.5 - 2.0 Hz)
  - joint_force   : force moteur (1.0 - 15.0 N)
  - max_velocity  : vitesse angulaire max (1.0 - 6.0 rad/s)
  - amp_hip       : amplitude hip (0.1 - 0.5 rad)
  - amp_knee      : amplitude knee (0.3 - 0.8 rad)
  - amp_ankle     : amplitude ankle (0.1 - 0.4 rad)

Usage :
  python -m askio1.simulation.cpg_tuner --proto proto1_tripod --iters 20
  python -m askio1.simulation.cpg_tuner --proto proto1_tripod --iters 50 --save-mea
"""

import json
import logging
import random
import time
from copy import deepcopy
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJ_DIR = Path(__file__).parent.parent.parent


@dataclass
class CPGParams:
    """Parametres tunables du CPG."""
    freq: float        = 1.0
    joint_force: float = 5.0
    max_velocity: float= 3.0
    amp_hip: float     = 0.25
    amp_knee: float    = 0.60
    amp_ankle: float   = 0.30
    gait: str          = "tripod_wave"

    def perturb(self, scale: float = 0.15) -> "CPGParams":
        """Retourne une copie avec perturbation aleatoire."""
        p = deepcopy(self)
        p.freq         = max(0.4, min(2.5, p.freq         + random.gauss(0, scale * 1.5)))
        p.joint_force  = max(1.0, min(20.0,p.joint_force  + random.gauss(0, scale * 8.0)))
        p.max_velocity = max(0.5, min(8.0, p.max_velocity + random.gauss(0, scale * 3.0)))
        p.amp_hip      = max(0.05,min(0.6, p.amp_hip      + random.gauss(0, scale * 0.2)))
        p.amp_knee     = max(0.2, min(1.0, p.amp_knee     + random.gauss(0, scale * 0.3)))
        p.amp_ankle    = max(0.05,min(0.5, p.amp_ankle    + random.gauss(0, scale * 0.2)))
        return p

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TuningResult:
    proto: str
    best_params: CPGParams
    best_score: float
    best_distance_m: float
    best_stability: float
    best_falls: int
    n_iterations: int
    duration_s_sim: float   # duree simulee par eval
    wall_time_s: float
    history: list = field(default_factory=list)  # [(score, params_dict)]
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class CPGTuner:
    """
    Tuner automatique par Random Search + Hill Climbing.

    Chaque evaluation = 1 simulation PyBullet de `sim_duration` secondes.
    Typiquement 3-5s par eval, 10-30 evals pour converger.
    """

    def __init__(self, proto: str = "proto1_tripod",
                 sim_duration: float = 4.0,
                 n_random: int = 8,
                 n_hillclimb: int = 12,
                 top_k: int = 3):
        self.proto        = proto
        self.sim_duration = sim_duration
        self.n_random     = n_random
        self.n_hillclimb  = n_hillclimb
        self.top_k        = top_k
        self.urdf_path    = PROJ_DIR / f"robot/{proto}/urdf/{proto}.urdf"

        if not self.urdf_path.exists():
            self._generate_urdf()

    def _generate_urdf(self):
        import sys; sys.path.insert(0, str(PROJ_DIR))
        from askio1.simulation.urdf_generator import URDFGenerator, PROTO_SPECS
        gen = URDFGenerator()
        proto_key = self.proto  # ex: proto1_tripod
        if proto_key not in PROTO_SPECS:
            raise ValueError(f"Proto inconnu: {proto_key}")
        urdf = gen.generate(proto_key)
        gen.save(urdf, self.urdf_path)
        logger.info(f"[Tuner] URDF genere : {self.urdf_path}")

    def _evaluate(self, params: CPGParams) -> dict:
        """Lance une simulation et retourne les metriques."""
        import sys; sys.path.insert(0, str(PROJ_DIR))
        import pybullet as pb
        import pybullet_data
        import math

        # Override les amplitudes dans le module CPG
        from askio1.simulation import cpg_controller as cpg_mod
        orig_amps    = dict(cpg_mod.JOINT_AMPLITUDES)
        orig_offsets = dict(cpg_mod.JOINT_OFFSETS)

        cpg_mod.JOINT_AMPLITUDES["hip"]   = params.amp_hip
        cpg_mod.JOINT_AMPLITUDES["knee"]  = params.amp_knee
        cpg_mod.JOINT_AMPLITUDES["ankle"] = params.amp_ankle

        try:
            from askio1.simulation.cpg_controller import CPGController

            TIMESTEP   = 0.002
            CPG_DT     = 0.01
            PHYS_PER_CPG = int(CPG_DT / TIMESTEP)

            client = pb.connect(pb.DIRECT)
            pb.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=client)
            pb.setGravity(0, 0, -9.81, physicsClientId=client)
            pb.setTimeStep(TIMESTEP,    physicsClientId=client)
            pb.setRealTimeSimulation(0, physicsClientId=client)
            pb.loadURDF("plane.urdf",   physicsClientId=client)

            robot = pb.loadURDF(str(self.urdf_path),
                                basePosition=[0, 0, 0.20],
                                flags=pb.URDF_USE_INERTIA_FROM_FILE,
                                physicsClientId=client)

            # Mappe joints
            joint_map = {}
            for i in range(pb.getNumJoints(robot, physicsClientId=client)):
                info = pb.getJointInfo(robot, i, physicsClientId=client)
                if info[2] == pb.JOINT_REVOLUTE:
                    joint_map[info[1].decode()] = i

            n_legs = 3 if "tripod" in self.proto else 4
            cpg    = CPGController(n_legs=n_legs, gait=params.gait,
                                   freq=params.freq, dt=CPG_DT)

            total_steps  = int(self.sim_duration / TIMESTEP)
            pos_history  = []
            orient_hist  = []
            energy_sum   = 0.0
            falls        = 0
            was_fallen   = False
            angles       = cpg.step()

            for step in range(total_steps):
                if step % PHYS_PER_CPG == 0:
                    angles = cpg.step()
                    for jname, angle in angles.items():
                        if jname in joint_map:
                            pb.setJointMotorControl2(
                                robot, joint_map[jname],
                                pb.POSITION_CONTROL,
                                targetPosition=angle,
                                force=params.joint_force,
                                maxVelocity=params.max_velocity,
                                physicsClientId=client,
                            )

                pb.stepSimulation(physicsClientId=client)

                if step % 10 == 0:
                    pos, quat = pb.getBasePositionAndOrientation(robot, physicsClientId=client)
                    roll, pitch, yaw = pb.getEulerFromQuaternion(quat)
                    pos_history.append(pos)
                    orient_hist.append((roll, pitch, yaw))

                    for idx in joint_map.values():
                        s = pb.getJointState(robot, idx, physicsClientId=client)
                        energy_sum += abs(s[3] * s[1]) * TIMESTEP * 10

                    if pos[2] < 0.04:
                        if not was_fallen:
                            falls += 1
                            was_fallen = True
                    else:
                        was_fallen = False

            pb.disconnect(physicsClientId=client)

            # Metriques
            if len(pos_history) >= 2:
                p0, p1 = pos_history[0], pos_history[-1]
                dist   = math.sqrt((p1[0]-p0[0])**2 + (p1[1]-p0[1])**2)
                speed  = dist / self.sim_duration

                rolls  = [o[0] for o in orient_hist]
                pitchs = [o[1] for o in orient_hist]
                var    = (max(rolls)-min(rolls) + max(pitchs)-min(pitchs)) / 2
                stability = max(0.0, 1.0 - var / (math.pi/4))
            else:
                dist, speed, stability = 0.0, 0.0, 0.0

            speed_norm  = min(speed / 0.5, 1.0)
            energy_norm = max(0.0, 1.0 - energy_sum / 20.0)
            score = max(0.0, 0.40*speed_norm + 0.40*stability + 0.10*energy_norm - 0.30*falls)

            return {"score": score, "distance": dist, "stability": stability,
                    "energy": energy_sum, "falls": falls}

        except Exception as e:
            logger.warning(f"[Tuner] eval failed: {e}")
            return {"score": 0.0, "distance": 0.0, "stability": 0.0,
                    "energy": 0.0, "falls": 99}
        finally:
            cpg_mod.JOINT_AMPLITUDES.update(orig_amps)

    def tune(self, seed: int = 42) -> TuningResult:
        random.seed(seed)
        t_start  = time.perf_counter()
        history  = []

        logger.info(f"[Tuner] debut — {self.proto} | random={self.n_random} hillclimb={self.n_hillclimb}")

        # Phase 1 : Random search
        candidates = []
        default = CPGParams()

        for i in range(self.n_random):
            params = default.perturb(scale=0.4) if i > 0 else default
            metrics= self._evaluate(params)
            score  = metrics["score"]
            candidates.append((score, params, metrics))
            history.append({"iter": i, "phase": "random", "score": round(score,4),
                            "params": params.to_dict(), **metrics})
            logger.info(f"[Tuner] random {i+1}/{self.n_random} — score={score:.4f} "
                        f"falls={metrics['falls']} dist={metrics['distance']:.3f}m")

        # Phase 2 : Hill climbing autour des top_k
        candidates.sort(key=lambda x: -x[0])
        top = candidates[:self.top_k]

        for i in range(self.n_hillclimb):
            base_score, base_params, _ = top[i % self.top_k]
            scale  = max(0.05, 0.25 * (1.0 - i / self.n_hillclimb))  # cooling
            params = base_params.perturb(scale=scale)
            metrics= self._evaluate(params)
            score  = metrics["score"]

            history.append({"iter": self.n_random + i, "phase": "hillclimb",
                            "score": round(score,4), "params": params.to_dict(), **metrics})
            logger.info(f"[Tuner] climb {i+1}/{self.n_hillclimb} — score={score:.4f} "
                        f"(base={base_score:.4f}) falls={metrics['falls']}")

            if score > top[0][0]:
                top.insert(0, (score, params, metrics))
                top = top[:self.top_k]
                logger.info(f"[Tuner] NOUVEAU MEILLEUR : {score:.4f}")

        best_score, best_params, best_metrics = top[0]
        wall_time = time.perf_counter() - t_start
        n_iters   = self.n_random + self.n_hillclimb

        result = TuningResult(
            proto=self.proto,
            best_params=best_params,
            best_score=round(best_score, 4),
            best_distance_m=round(best_metrics["distance"], 4),
            best_stability=round(best_metrics["stability"], 4),
            best_falls=best_metrics["falls"],
            n_iterations=n_iters,
            duration_s_sim=self.sim_duration,
            wall_time_s=round(wall_time, 1),
            history=history,
        )

        logger.info(f"[Tuner] termine en {wall_time:.1f}s — meilleur score={best_score:.4f}")
        logger.info(f"[Tuner] meilleurs params : {best_params.to_dict()}")
        return result

    def save_result(self, result: TuningResult, save_mea: bool = False) -> Path:
        out_dir = PROJ_DIR / "data/artifacts/report"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"tuning_{self.proto}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        data = {
            "proto": result.proto,
            "best_score": result.best_score,
            "best_params": result.best_params.to_dict(),
            "best_distance_m": result.best_distance_m,
            "best_stability": result.best_stability,
            "best_falls": result.best_falls,
            "n_iterations": result.n_iterations,
            "wall_time_s": result.wall_time_s,
            "timestamp": result.timestamp,
            "history": result.history,
        }
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"[Tuner] resultats sauvegardes : {out}")

        # Sauvegarde dans la MEA
        if save_mea:
            try:
                import sys, uuid
                sys.path.insert(0, str(PROJ_DIR))
                import yaml
                from askio1.memory.store import MemoryStore
                from askio1.memory.schemas import MemoryEntry
                config = yaml.safe_load(open(PROJ_DIR / "config.yaml"))
                store  = MemoryStore(config)
                entry  = MemoryEntry(
                    id=str(uuid.uuid4())[:8],
                    type="tuning_result",
                    scope="simulation",
                    context={"proto": result.proto, "path": str(out)},
                    summary=f"[tuning] {result.proto} — score={result.best_score} "
                            f"falls={result.best_falls} dist={result.best_distance_m}m",
                    details=json.dumps(result.best_params.to_dict()),
                    links=[str(out)],
                    importance="high",
                    created_at=result.timestamp,
                )
                store.save_entry(entry)
                logger.info("[Tuner] entree MEA sauvegardee")
            except Exception as e:
                logger.warning(f"[Tuner] MEA save failed: {e}")

        return out


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s - %(message)s")

    parser = argparse.ArgumentParser(description="CPG Tuner - Askio1 v2")
    parser.add_argument("--proto",    default="proto1_tripod",
                        choices=["proto1_tripod", "proto2_quad"])
    parser.add_argument("--iters",    type=int,   default=20,
                        help="Nombre total d'iterations (random + hillclimb)")
    parser.add_argument("--dur",      type=float, default=4.0,
                        help="Duree simulee par evaluation (s)")
    parser.add_argument("--save-mea", action="store_true",
                        help="Sauvegarde les meilleurs params dans la MEA")
    parser.add_argument("--seed",     type=int,   default=42)
    args = parser.parse_args()

    n_random    = max(3, args.iters // 3)
    n_hillclimb = args.iters - n_random

    tuner = CPGTuner(
        proto=args.proto,
        sim_duration=args.dur,
        n_random=n_random,
        n_hillclimb=n_hillclimb,
    )

    print(f"\nTuning CPG — {args.proto} | {args.iters} evals x {args.dur}s ...")
    result = tuner.tune(seed=args.seed)
    out    = tuner.save_result(result, save_mea=args.save_mea)

    print(f"\n=== RESULTATS ===")
    print(f"Score    : {result.best_score}")
    print(f"Distance : {result.best_distance_m}m")
    print(f"Stabilite: {result.best_stability}")
    print(f"Chutes   : {result.best_falls}")
    print(f"Temps    : {result.wall_time_s}s ({args.iters} evals)")
    print(f"\nMeilleurs params :")
    for k, v in result.best_params.to_dict().items():
        print(f"  {k:15} = {v}")
    print(f"\nSauvegarde : {out}")
