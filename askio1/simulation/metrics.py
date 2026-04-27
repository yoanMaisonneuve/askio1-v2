"""
metrics.py — Métriques de simulation robot (Phase 10)
=====================================================
Calcule et enregistre les métriques de performance pendant la simulation.

Métriques trackées :
  - Distance parcourue (m) — depuis position initiale
  - Stabilité (°) — variation d'orientation du corps
  - Énergie mécanique (J) — somme |couple × vitesse angulaire|
  - Chutes — nombre de fois que le robot touche le sol avec le corps
  - Score global — combinaison pondérée

Peut fonctionner :
  1. Standalone : lit un CSV de trajectoire CPG et estime les métriques
  2. ROS2 : subscribe à /odom et /joint_states pour métriques réelles

Usage standalone :
  python -m askio1.simulation.metrics --csv data/artifacts/simulation/cpg_proto1_tripod_wave.csv
"""

import csv
import json
import logging
import math
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


# ─── Structures de données ────────────────────────────────────────────────────

@dataclass
class SimFrame:
    """Un instant de simulation."""
    t: float
    joint_angles: dict        # {joint_name: angle_rad}
    body_pos: tuple = (0., 0., 0.)    # x, y, z
    body_orient: tuple = (0., 0., 0.) # roll, pitch, yaw (rad)


@dataclass
class SimMetrics:
    """Résultat d'une session de simulation."""
    proto: str = "unknown"
    gait: str = "unknown"
    duration_s: float = 0.0
    distance_m: float = 0.0
    forward_speed_ms: float = 0.0
    stability_score: float = 0.0      # 0-1 (1 = parfaitement stable)
    energy_J: float = 0.0
    falls: int = 0
    global_score: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def summary(self) -> str:
        return (
            f"Proto={self.proto} Gait={self.gait} | "
            f"Distance={self.distance_m:.3f}m "
            f"Speed={self.forward_speed_ms:.3f}m/s "
            f"Stability={self.stability_score:.2f} "
            f"Energy={self.energy_J:.2f}J "
            f"Falls={self.falls} "
            f"Score={self.global_score:.3f}"
        )


# ─── Tracker de métriques ─────────────────────────────────────────────────────

class MetricsTracker:
    """
    Accumule les frames de simulation et calcule les métriques.

    Peut être utilisé en mode streaming (frame par frame) ou batch (liste CSV).
    """

    def __init__(self, proto: str = "proto1", gait: str = "tripod_wave"):
        self.proto = proto
        self.gait  = gait
        self.frames: List[SimFrame] = []
        self._orient_history = deque(maxlen=50)  # pour stabilité

    def add_frame(self, frame: SimFrame):
        self.frames.append(frame)
        self._orient_history.append(frame.body_orient)

    def compute(self) -> SimMetrics:
        """Calcule toutes les métriques depuis les frames accumulées."""
        if not self.frames:
            return SimMetrics(proto=self.proto, gait=self.gait)

        duration = self.frames[-1].t - self.frames[0].t
        if duration <= 0:
            duration = len(self.frames) * 0.01

        metrics = SimMetrics(
            proto=self.proto,
            gait=self.gait,
            duration_s=round(duration, 3),
        )

        metrics.distance_m      = self._compute_distance()
        metrics.forward_speed_ms= round(metrics.distance_m / duration, 4) if duration > 0 else 0.0
        metrics.stability_score = self._compute_stability()
        metrics.energy_J        = self._compute_energy()
        metrics.falls           = self._count_falls()
        metrics.global_score    = self._compute_global_score(metrics)

        logger.info(f"[Metrics] {metrics.summary()}")
        return metrics

    def _compute_distance(self) -> float:
        """Distance totale parcourue (norme 3D entre premier et dernier point)."""
        if len(self.frames) < 2:
            return 0.0
        p0 = self.frames[0].body_pos
        p1 = self.frames[-1].body_pos
        return round(math.sqrt(sum((a-b)**2 for a, b in zip(p0, p1))), 4)

    def _compute_stability(self) -> float:
        """
        Stabilité = 1 - (variation d'orientation normalisée).
        Proche de 1 → robot stable. Proche de 0 → robot chaotique.
        """
        if len(self.frames) < 5:
            return 1.0

        rolls  = [f.body_orient[0] for f in self.frames]
        pitchs = [f.body_orient[1] for f in self.frames]

        roll_var  = max(rolls)  - min(rolls)
        pitch_var = max(pitchs) - min(pitchs)

        # Normalise sur π/4 (45°) comme référence d'instabilité
        max_var = math.pi / 4
        stability = 1.0 - min((roll_var + pitch_var) / (2 * max_var), 1.0)
        return round(stability, 4)

    def _compute_energy(self) -> float:
        """
        Énergie mécanique estimée : somme des |Δangle| × masse_equiv.
        Proxy de la consommation énergétique (sans vrais couples).
        """
        if len(self.frames) < 2:
            return 0.0

        total_energy = 0.0
        inertia_proxy = 0.05  # kg·m² simplifié par joint

        for i in range(1, len(self.frames)):
            f0, f1 = self.frames[i-1], self.frames[i]
            dt = max((f1.t - f0.t), 1e-6)
            for joint in f0.joint_angles:
                if joint in f1.joint_angles:
                    delta = abs(f1.joint_angles[joint] - f0.joint_angles[joint])
                    omega = delta / dt  # vitesse angulaire approx
                    total_energy += 0.5 * inertia_proxy * omega**2 * dt

        return round(total_energy, 4)

    def _count_falls(self) -> int:
        """Chutes = nombre de fois que z < seuil (corps trop bas)."""
        min_height = 0.05  # m — si le corps descend sous 5cm → chute
        falls = 0
        was_fallen = False
        for f in self.frames:
            if f.body_pos[2] < min_height:
                if not was_fallen:
                    falls += 1
                    was_fallen = True
            else:
                was_fallen = False
        return falls

    def _compute_global_score(self, m: SimMetrics) -> float:
        """
        Score global = combinaison pondérée des métriques.
        W : vitesse 0.4, stabilité 0.4, énergie 0.1 (inversé), chutes -0.3/chute.
        """
        # Normalise vitesse sur 0.5 m/s comme référence
        speed_norm  = min(m.forward_speed_ms / 0.5, 1.0)
        energy_norm = max(0.0, 1.0 - m.energy_J / 10.0)  # ref 10J = mauvais

        score = (
            0.40 * speed_norm
            + 0.40 * m.stability_score
            + 0.10 * energy_norm
            - 0.30 * m.falls
        )
        return round(max(0.0, score), 4)

    def save(self, path: str | Path) -> Path:
        """Sauvegarde les métriques en JSON."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        metrics = self.compute()
        p.write_text(json.dumps(asdict(metrics), indent=2, ensure_ascii=False),
                     encoding="utf-8")
        logger.info(f"[Metrics] sauvegardé : {p}")
        return p


# ─── Analyse depuis CSV CPG ───────────────────────────────────────────────────

def analyze_cpg_csv(csv_path: str, proto: str = "proto1",
                    gait: str = "tripod_wave") -> SimMetrics:
    """
    Lit un CSV de trajectoire CPG et estime les métriques.
    Comme on n'a pas de simulation physique, on estime la position
    à partir des angles joints (cinématique directe simplifiée).
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV introuvable : {csv_path}")

    tracker = MetricsTracker(proto=proto, gait=gait)

    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        x, y, z = 0.0, 0.0, 0.15  # position initiale estimée

        for row in reader:
            t = float(row["t"])
            angles = {k: float(v) for k, v in row.items() if k != "t"}

            # Estimation très grossière du déplacement depuis les angles de knee
            # Modèle simplifié : knee fléchi → pousse vers l'avant
            avg_knee = sum(v for k, v in angles.items() if "knee" in k)
            avg_knee /= max(sum(1 for k in angles if "knee" in k), 1)

            # Vitesse forward estimée depuis angle knee (proxy)
            dx = max(0, -avg_knee - 0.6) * 0.02  # knee fléchi > 0.6 rad → avance
            x += dx

            frame = SimFrame(
                t=t,
                joint_angles=angles,
                body_pos=(x, y, z),
                body_orient=(
                    math.sin(t * 0.5) * 0.03,   # roll oscillant léger
                    math.sin(t * 1.0) * 0.05,   # pitch oscillant
                    0.0,
                ),
            )
            tracker.add_frame(frame)

    return tracker.compute()


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s — %(message)s")

    parser = argparse.ArgumentParser(description="Métriques simulation — Askio1 v2")
    parser.add_argument("--csv",   required=True, help="Fichier CSV trajectoire CPG")
    parser.add_argument("--proto", default="proto1")
    parser.add_argument("--gait",  default="tripod_wave")
    parser.add_argument("--out",   default=None, help="Fichier JSON de sortie")
    args = parser.parse_args()

    print(f"\n📊 Analyse métriques : {args.csv}")
    metrics = analyze_cpg_csv(args.csv, proto=args.proto, gait=args.gait)
    print(f"\n{metrics.summary()}")
    print(f"\nDétail :")
    print(f"  Durée        : {metrics.duration_s:.2f}s")
    print(f"  Distance     : {metrics.distance_m:.4f}m")
    print(f"  Vitesse      : {metrics.forward_speed_ms:.4f}m/s")
    print(f"  Stabilité    : {metrics.stability_score:.4f}")
    print(f"  Énergie est. : {metrics.energy_J:.4f}J")
    print(f"  Chutes       : {metrics.falls}")
    print(f"  Score global : {metrics.global_score:.4f}")

    if args.out:
        out = Path(args.out)
    else:
        out = Path(f"data/artifacts/report/metrics_{args.proto}_{args.gait}.json")

    out.parent.mkdir(parents=True, exist_ok=True)
    import json, dataclasses
    out.write_text(json.dumps(dataclasses.asdict(metrics), indent=2), encoding="utf-8")
    print(f"\n✓ Sauvegardé : {out}")
