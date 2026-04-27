"""
cpg_controller.py — Contrôleur CPG (Central Pattern Generator) — Phase 9
=========================================================================
Génère des trajectoires de joints pour la locomotion du robot.

Un CPG est un réseau d'oscillateurs couplés qui produit des patterns
rythmiques sans input sensoriel — c'est ce que la moelle épinière fait
pour la marche chez les animaux.

Implémentation :
  - Oscillateurs de Hopf (amplitude + phase stables)
  - Couplage inter-oscillateurs via matrice de phase
  - Génère des angles joints en radians pour chaque pas de temps

Gaits supportés :
  tripod_static  — gait tripode statique (1 patte à la fois)
  tripod_wave    — gait onde (PROTO-1, stable et lent)
  trot           — gait trot diagonale (PROTO-2)

Usage standalone :
  python -m askio1.simulation.cpg_controller --proto proto1 --gait tripod_wave --steps 200
  → affiche les angles joints + sauvegarde CSV

Usage ROS2 (quand installé) :
  Hérite de Node, publie sur /joint_commands (std_msgs/Float64MultiArray)
"""

import math
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─── Oscillateur de Hopf ──────────────────────────────────────────────────────

@dataclass
class HopfOscillator:
    """
    Oscillateur de Hopf :
      dx/dt = (mu - r²) * x - omega * y
      dy/dt = (mu - r²) * y + omega * x
    où r = sqrt(x² + y²), mu = amplitude cible au carré.

    En pratique, on intègre avec Euler et on lit la phase.
    """
    omega: float = 2.0      # fréquence angulaire (rad/s)
    mu: float = 1.0         # amplitude cible
    x: float = 0.1          # état initial x
    y: float = 0.0          # état initial y
    coupling_strength: float = 0.5

    @property
    def amplitude(self) -> float:
        return math.sqrt(self.x**2 + self.y**2)

    @property
    def phase(self) -> float:
        return math.atan2(self.y, self.x)

    def step(self, dt: float, external: float = 0.0):
        r2 = self.x**2 + self.y**2
        dx = (self.mu - r2) * self.x - self.omega * self.y + external
        dy = (self.mu - r2) * self.y + self.omega * self.x
        self.x += dx * dt
        self.y += dy * dt


# ─── Configs gait ─────────────────────────────────────────────────────────────

# Décalages de phase (rad) entre oscillateurs pour chaque gait
# Pour PROTO-1 tripode : 3 oscillateurs (leg1, leg2, leg3)
GAIT_PHASES = {
    "tripod_static": [0.0, 2*math.pi/3, 4*math.pi/3],     # 120° entre pattes
    "tripod_wave":   [0.0, math.pi/3,   2*math.pi/3],      # onde progressive
    "trot":          [0.0, math.pi,     0.0, math.pi],      # diagonal sync (quad)
    "walk":          [0.0, math.pi/2,   math.pi, 3*math.pi/2],  # onde quad
}

# Amplitude par joint (fraction de l'amplitude CPG)
JOINT_AMPLITUDES = {
    "hip":   0.25,   # rad — abduction/adduction
    "knee":  0.60,   # rad — flexion/extension principale
    "ankle": 0.30,   # rad — compensation contact sol
}

# Offset (posture neutre) par joint
JOINT_OFFSETS = {
    "hip":   0.0,
    "knee":  -0.7,   # légèrement fléchi
    "ankle":  0.3,
}


# ─── Contrôleur CPG ───────────────────────────────────────────────────────────

class CPGController:
    """
    Réseau CPG pour robot multi-pattes.

    Paramètres :
      n_legs    : nombre de pattes (3 ou 4)
      gait      : nom du gait (voir GAIT_PHASES)
      freq      : fréquence de gait (Hz) — pas par seconde
      dt        : pas de temps simulation (s)
    """

    def __init__(self, n_legs: int = 3, gait: str = "tripod_wave",
                 freq: float = 1.0, dt: float = 0.01):
        self.n_legs = n_legs
        self.gait   = gait
        self.dt     = dt
        self.t      = 0.0

        omega = 2 * math.pi * freq
        phases = GAIT_PHASES.get(gait, GAIT_PHASES["tripod_wave"])

        # Un oscillateur par patte
        self.oscillators: List[HopfOscillator] = []
        for i in range(n_legs):
            phi = phases[i % len(phases)]
            osc = HopfOscillator(omega=omega, mu=1.0,
                                 x=math.cos(phi) * 0.1,
                                 y=math.sin(phi) * 0.1)
            self.oscillators.append(osc)

        logger.info(f"[CPG] init — {n_legs} pattes, gait={gait}, freq={freq}Hz, dt={dt}s")

    def step(self) -> Dict[str, float]:
        """
        Avance d'un pas de temps.
        Retourne : dict {joint_name: angle_rad}
        """
        # Calcul du couplage inter-oscillateurs
        externals = self._compute_coupling()

        # Mise à jour de chaque oscillateur
        for i, osc in enumerate(self.oscillators):
            osc.step(self.dt, externals[i])

        self.t += self.dt
        return self._compute_joint_angles()

    def _compute_coupling(self) -> List[float]:
        """Couplage par différence de phase entre oscillateurs voisins."""
        n = len(self.oscillators)
        externals = [0.0] * n
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                osc_i = self.oscillators[i]
                osc_j = self.oscillators[j]
                # Force de couplage : proportionnelle au sin de la différence de phase
                phi_i = osc_i.phase
                phi_j = osc_j.phase
                weight = osc_i.coupling_strength / (n - 1)
                externals[i] += weight * math.sin(phi_j - phi_i)
        return externals

    def _compute_joint_angles(self) -> Dict[str, float]:
        """Convertit les états CPG en angles joints."""
        angles = {}
        for i, osc in enumerate(self.oscillators):
            leg = f"leg{i+1}"
            x, y = osc.x, osc.y
            r = osc.amplitude

            # Hip : couplé à la composante y (latéral)
            angles[f"{leg}_hip"] = (
                JOINT_OFFSETS["hip"] + JOINT_AMPLITUDES["hip"] * y
            )

            # Knee : couplé à la composante x (avant/arrière)
            # Phase shift de pi/2 pour le genou (contact sol)
            knee_x = x * math.cos(math.pi/2) - y * math.sin(math.pi/2)
            angles[f"{leg}_knee"] = (
                JOINT_OFFSETS["knee"] + JOINT_AMPLITUDES["knee"] * knee_x
            )

            # Ankle : opposition de phase avec le genou
            angles[f"{leg}_ankle"] = (
                JOINT_OFFSETS["ankle"] - JOINT_AMPLITUDES["ankle"] * knee_x * 0.5
            )

        return angles

    def run(self, duration: float) -> List[Dict[str, float]]:
        """Génère une trajectoire complète sur `duration` secondes."""
        trajectory = []
        n_steps = int(duration / self.dt)
        for _ in range(n_steps):
            trajectory.append(self.step())
        logger.info(f"[CPG] trajectoire générée — {n_steps} steps, {duration}s")
        return trajectory

    def save_csv(self, trajectory: List[Dict[str, float]], path: str):
        """Sauvegarde la trajectoire en CSV pour analyse/visualisation."""
        from pathlib import Path
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if not trajectory:
            return
        headers = ["t"] + list(trajectory[0].keys())
        rows = []
        for i, angles in enumerate(trajectory):
            row = [round(i * self.dt, 4)] + [round(v, 5) for v in angles.values()]
            rows.append(row)
        with open(p, "w", encoding="utf-8") as f:
            f.write(",".join(headers) + "\n")
            for row in rows:
                f.write(",".join(map(str, row)) + "\n")
        logger.info(f"[CPG] trajectoire sauvegardée : {p}")


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s — %(message)s")

    parser = argparse.ArgumentParser(description="CPG Controller — Askio1 v2")
    parser.add_argument("--proto",  default="proto1", choices=["proto1", "proto2"])
    parser.add_argument("--gait",   default="tripod_wave", choices=list(GAIT_PHASES))
    parser.add_argument("--freq",   type=float, default=1.0,  help="Fréquence de pas (Hz)")
    parser.add_argument("--dur",    type=float, default=5.0,  help="Durée (secondes)")
    parser.add_argument("--dt",     type=float, default=0.01, help="Pas de temps (s)")
    parser.add_argument("--csv",    default=None, help="Sauvegarder trajectoire CSV")
    args = parser.parse_args()

    n_legs = 3 if args.proto == "proto1" else 4

    ctrl = CPGController(n_legs=n_legs, gait=args.gait,
                         freq=args.freq, dt=args.dt)
    traj = ctrl.run(args.dur)

    # Affiche les 5 premiers pas
    print(f"\n[CPG] {len(traj)} steps — premiers pas :")
    print(f"{'t':>6}  " + "  ".join(f"{k:>12}" for k in traj[0].keys()))
    for i in range(min(5, len(traj))):
        vals = "  ".join(f"{v:>12.4f}" for v in traj[i].values())
        print(f"{i*args.dt:>6.3f}  {vals}")
    print("  ...")

    if args.csv:
        ctrl.save_csv(traj, args.csv)
    else:
        out = f"data/artifacts/simulation/cpg_{args.proto}_{args.gait}.csv"
        ctrl.save_csv(traj, out)
        print(f"\nSauvegardé : {out}")
