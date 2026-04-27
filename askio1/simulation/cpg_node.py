"""
cpg_node.py — Nœud ROS2 CPG Controller (Phase 10)
===================================================
Publie les angles joints en temps réel dans Gazebo via ROS2.

Topics publiés :
  /joint_commands  (std_msgs/Float64MultiArray) — angles joints CPG
  /cpg_state       (std_msgs/String, JSON)      — état interne oscillateurs

Topics souscrits :
  /robot_state     (sensor_msgs/JointState)     — feedback positions réelles

Usage (ROS2 Humble installé) :
  ros2 run askio1_robot cpg_node --ros-args -p gait:=tripod_wave -p freq:=1.0

Mode standalone (test sans ROS2) :
  python -m askio1.simulation.cpg_node --standalone --dur 5.0
"""

import json
import logging
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)


# ─── Nœud ROS2 ───────────────────────────────────────────────────────────────

def run_ros2_node():
    """Lance le nœud ROS2 si rclpy est disponible."""
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import Float64MultiArray, String
    from sensor_msgs.msg import JointState
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from askio1.simulation.cpg_controller import CPGController

    class CPGNode(Node):
        def __init__(self):
            super().__init__("cpg_node")

            # Paramètres ROS2
            self.declare_parameter("n_legs", 3)
            self.declare_parameter("gait",   "tripod_wave")
            self.declare_parameter("freq",   1.0)
            self.declare_parameter("dt",     0.01)
            self.declare_parameter("proto",  "proto1")

            n_legs = self.get_parameter("n_legs").value
            gait   = self.get_parameter("gait").value
            freq   = self.get_parameter("freq").value
            dt     = self.get_parameter("dt").value

            self.cpg = CPGController(n_legs=n_legs, gait=gait, freq=freq, dt=dt)
            self.joint_names = list(self.cpg.step().keys())
            # Reset après le step de test
            from askio1.simulation.cpg_controller import CPGController as _C
            self.cpg = _C(n_legs=n_legs, gait=gait, freq=freq, dt=dt)

            # Publishers
            self.pub_joints = self.create_publisher(
                Float64MultiArray, "/joint_commands", 10)
            self.pub_state = self.create_publisher(
                String, "/cpg_state", 10)

            # Subscriber feedback
            self.sub_state = self.create_subscription(
                JointState, "/joint_states",
                self._joint_state_cb, 10)

            # Timer principal
            self.timer = self.create_timer(dt, self._timer_cb)
            self.get_logger().info(
                f"[CPGNode] démarré — gait={gait} freq={freq}Hz dt={dt}s"
            )

        def _timer_cb(self):
            angles = self.cpg.step()

            # Publish joint commands
            msg = Float64MultiArray()
            msg.data = [angles[j] for j in self.joint_names]
            self.pub_joints.publish(msg)

            # Publish état interne (JSON) tous les 10 cycles
            if int(self.cpg.t / self.cpg.dt) % 10 == 0:
                state = {
                    "t": round(self.cpg.t, 3),
                    "oscillators": [
                        {"amp": round(o.amplitude, 4), "phase": round(o.phase, 4)}
                        for o in self.cpg.oscillators
                    ],
                }
                msg_s = String()
                msg_s.data = json.dumps(state)
                self.pub_state.publish(msg_s)

        def _joint_state_cb(self, msg: "JointState"):
            # Feedback pour futures corrections (Phase 11 RL)
            pass

    rclpy.init()
    node = CPGNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


# ─── Mode standalone (test sans ROS2) ────────────────────────────────────────

def run_standalone(dur: float = 5.0, gait: str = "tripod_wave",
                   n_legs: int = 3, freq: float = 1.0, dt: float = 0.01):
    """Simule le nœud sans ROS2 — affiche les angles en temps réel."""
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from askio1.simulation.cpg_controller import CPGController

    ctrl  = CPGController(n_legs=n_legs, gait=gait, freq=freq, dt=dt)
    steps = int(dur / dt)

    print(f"\n[CPG Standalone] gait={gait} freq={freq}Hz dur={dur}s — {steps} steps")
    print(f"Joints : {list(ctrl.step().keys())}")
    ctrl  = CPGController(n_legs=n_legs, gait=gait, freq=freq, dt=dt)  # reset

    print(f"\n{'t':>6}  {'leg1_knee':>10}  {'leg2_knee':>10}  {'leg3_knee':>10}  {'rate':>8}")
    print("─" * 50)

    t0 = time.perf_counter()
    for i in range(steps):
        t_start = time.perf_counter()
        angles  = ctrl.step()
        elapsed = time.perf_counter() - t_start
        rate    = 1.0 / elapsed if elapsed > 0 else 99999

        # Affiche 1 ligne par 50 ms de simulation
        if i % int(0.05 / dt) == 0:
            print(
                f"{ctrl.t:>6.3f}  "
                f"{angles.get('leg1_knee', 0):>10.4f}  "
                f"{angles.get('leg2_knee', 0):>10.4f}  "
                f"{angles.get('leg3_knee', 0):>10.4f}  "
                f"{rate:>8.0f}/s"
            )

        # Simule la cadence temps réel
        sleep_t = dt - (time.perf_counter() - t_start)
        if sleep_t > 0:
            time.sleep(sleep_t)

    total = time.perf_counter() - t0
    print(f"\n✓ {steps} steps en {total:.2f}s — fréquence réelle: {steps/total:.1f} Hz")


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s — %(message)s")

    parser = argparse.ArgumentParser(description="CPG Node — Askio1 v2")
    parser.add_argument("--standalone", action="store_true",
                        help="Mode sans ROS2 (test local)")
    parser.add_argument("--gait",   default="tripod_wave")
    parser.add_argument("--freq",   type=float, default=1.0)
    parser.add_argument("--dur",    type=float, default=5.0)
    parser.add_argument("--n-legs", type=int,   default=3)
    parser.add_argument("--dt",     type=float, default=0.01)
    args = parser.parse_args()

    if args.standalone:
        run_standalone(dur=args.dur, gait=args.gait,
                       n_legs=args.n_legs, freq=args.freq, dt=args.dt)
    else:
        try:
            run_ros2_node()
        except ImportError:
            print("[CPGNode] rclpy non disponible — utilise --standalone pour tester")
            run_standalone(dur=args.dur, gait=args.gait,
                           n_legs=args.n_legs, freq=args.freq, dt=args.dt)
