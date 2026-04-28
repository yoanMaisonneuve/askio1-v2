"""
demo_3d.py — Visualisation 3D PyBullet du robot Askio1 (pour enregistrement OBS)
=================================================================================
Lance la simulation PyBullet en mode GUI avec une caméra orbitale.
Le robot marche en boucle avec les meilleurs paramètres CPG disponibles.

Usage :
  python3 demo_3d.py
  python3 demo_3d.py --proto proto2_quad --gait trot
  python3 demo_3d.py --loops 0   # 0 = infini
"""

import argparse
import json
import logging
import math
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s")
logger = logging.getLogger("askio1.demo3d")

PROJ_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJ_DIR))


def load_best_params(proto: str) -> dict:
    """Charge les meilleurs paramètres CPG depuis les résultats de tuning."""
    report_dir = PROJ_DIR / "data/artifacts/report"
    pattern = f"tuning_{proto}_*.json"
    files = sorted(report_dir.glob(pattern))
    if files:
        data = json.loads(files[-1].read_text(encoding="utf-8"))
        logger.info(f"[Demo3D] paramètres chargés depuis {files[-1].name}")
        return data.get("best_params", {})
    logger.info("[Demo3D] pas de tuning trouvé — paramètres par défaut")
    return {}


def run_demo(proto: str = "proto1_tripod", gait: str = "tripod_wave",
             loops: int = 0, duration_per_loop: float = 10.0):
    """Lance la simulation PyBullet en mode GUI en boucle."""
    import pybullet as pb
    import pybullet_data

    from askio1.simulation.urdf_generator import URDFGenerator
    from askio1.simulation.cpg_controller import CPGController, JOINT_AMPLITUDES

    # Charge ou génère l'URDF
    urdf_path = PROJ_DIR / f"robot/{proto}/urdf/{proto}.urdf"
    if not urdf_path.exists():
        logger.info(f"[Demo3D] génération URDF {proto}...")
        gen = URDFGenerator()
        urdf = gen.generate(proto)
        gen.save(urdf, urdf_path)

    # Charge les meilleurs paramètres CPG si disponibles
    best = load_best_params(proto)
    freq       = best.get("freq",         1.0)
    joint_force= best.get("joint_force",  5.0)
    max_vel    = best.get("max_velocity", 3.0)
    if "amp_hip" in best:
        JOINT_AMPLITUDES["hip"]   = best["amp_hip"]
        JOINT_AMPLITUDES["knee"]  = best["amp_knee"]
        JOINT_AMPLITUDES["ankle"] = best["amp_ankle"]

    logger.info(f"[Demo3D] {proto}/{gait} freq={freq} force={joint_force} vel={max_vel}")

    # Connexion PyBullet GUI
    client = pb.connect(pb.GUI)
    pb.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=client)
    pb.setGravity(0, 0, -9.81, physicsClientId=client)
    pb.setTimeStep(0.002,       physicsClientId=client)
    pb.setRealTimeSimulation(0, physicsClientId=client)

    # Caméra initiale — vue 3/4 du robot
    pb.resetDebugVisualizerCamera(
        cameraDistance=0.6,
        cameraYaw=45,
        cameraPitch=-20,
        cameraTargetPosition=[0, 0, 0.1],
        physicsClientId=client,
    )
    pb.configureDebugVisualizer(pb.COV_ENABLE_SHADOWS, 1, physicsClientId=client)
    pb.configureDebugVisualizer(pb.COV_ENABLE_RGB_BUFFER_PREVIEW, 0, physicsClientId=client)

    # Sol
    pb.loadURDF("plane.urdf", physicsClientId=client)

    loop_count = 0
    while loops == 0 or loop_count < loops:
        loop_count += 1
        logger.info(f"[Demo3D] boucle {loop_count} — {duration_per_loop}s")

        # (Re)charge le robot au début de chaque boucle
        robot = pb.loadURDF(
            str(urdf_path),
            basePosition=[0, 0, 0.20],
            baseOrientation=pb.getQuaternionFromEuler([0, 0, 0]),
            flags=pb.URDF_USE_INERTIA_FROM_FILE,
            physicsClientId=client,
        )

        # Mappe joints
        joint_map = {}
        for i in range(pb.getNumJoints(robot, physicsClientId=client)):
            info = pb.getJointInfo(robot, i, physicsClientId=client)
            if info[2] == pb.JOINT_REVOLUTE:
                joint_map[info[1].decode()] = i

        n_legs = 3 if "tripod" in proto else 4
        cpg    = CPGController(n_legs=n_legs, gait=gait, freq=freq, dt=0.01)

        TIMESTEP     = 0.002
        CPG_DT       = 0.01
        PHYS_PER_CPG = int(CPG_DT / TIMESTEP)
        total_steps  = int(duration_per_loop / TIMESTEP)

        angles     = cpg.step()
        cam_yaw    = 45.0  # rotation lente de caméra

        for step in range(total_steps):
            if step % PHYS_PER_CPG == 0:
                angles = cpg.step()
                for jname, angle in angles.items():
                    if jname in joint_map:
                        pb.setJointMotorControl2(
                            robot, joint_map[jname],
                            pb.POSITION_CONTROL,
                            targetPosition=angle,
                            force=joint_force,
                            maxVelocity=max_vel,
                            physicsClientId=client,
                        )

            pb.stepSimulation(physicsClientId=client)

            # Caméra orbitale lente (1 tour en ~30s)
            if step % 100 == 0:
                cam_yaw = (cam_yaw + 0.3) % 360
                pos, _ = pb.getBasePositionAndOrientation(robot, physicsClientId=client)
                pb.resetDebugVisualizerCamera(
                    cameraDistance=0.6,
                    cameraYaw=cam_yaw,
                    cameraPitch=-20,
                    cameraTargetPosition=list(pos),
                    physicsClientId=client,
                )

            # ~500 Hz → limiter à environ temps réel pour la démo visuelle
            if step % 50 == 0:
                time.sleep(0.0001)

        # Retire le robot avant la prochaine boucle
        pb.removeBody(robot, physicsClientId=client)
        logger.info(f"[Demo3D] boucle {loop_count} terminée")

    pb.disconnect(physicsClientId=client)
    logger.info("[Demo3D] terminé")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Démo 3D PyBullet — Askio1 v2")
    parser.add_argument("--proto", default="proto1_tripod",
                        choices=["proto1_tripod", "proto2_quad"])
    parser.add_argument("--gait",  default="tripod_wave")
    parser.add_argument("--loops", type=int, default=0, help="0 = infini")
    parser.add_argument("--dur",   type=float, default=15.0,
                        help="Durée par boucle (secondes simulées)")
    args = parser.parse_args()

    print(f"\n🤖 Askio1 Demo 3D — {args.proto}/{args.gait}")
    print("   Caméra orbitale automatique — enregistre avec OBS")
    print("   Ctrl+C pour arrêter\n")

    try:
        run_demo(proto=args.proto, gait=args.gait,
                 loops=args.loops, duration_per_loop=args.dur)
    except KeyboardInterrupt:
        print("\nArrêt propre.")
