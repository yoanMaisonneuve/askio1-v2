"""
urdf_generator.py — Générateur URDF automatique (Phase 9)
==========================================================
Génère des fichiers URDF valides pour Gazebo à partir de
spécifications paramétriques stockées dans la MEA.

Prototypes supportés :
  proto1_tripod  — 3 pattes, 9 DOF (3 joints par patte)
  proto2_quad    — 4 pattes, 12 DOF

Usage :
  from askio1.simulation.urdf_generator import URDFGenerator
  gen = URDFGenerator()
  urdf = gen.generate("proto1_tripod")
  gen.save(urdf, "data/artifacts/simulation/proto1_tripod.urdf")

  # Depuis la ligne de commande :
  python -m askio1.simulation.urdf_generator --proto proto1_tripod
"""

import math
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


# ─── Specs paramétriques ──────────────────────────────────────────────────────

@dataclass
class LinkSpec:
    name: str
    length: float        # m
    radius: float        # m (cylindre)
    mass: float          # kg
    color_rgba: str = "0.3 0.3 0.8 1.0"


@dataclass
class JointSpec:
    name: str
    parent: str
    child: str
    joint_type: str      # revolute | continuous | fixed
    axis_xyz: str        # ex: "0 1 0"
    origin_xyz: str      # ex: "0 0 -0.05"
    origin_rpy: str = "0 0 0"
    lower: float = -1.57
    upper: float = 1.57
    effort: float = 10.0
    velocity: float = 2.0


@dataclass
class RobotSpec:
    name: str
    body_radius: float
    body_height: float
    body_mass: float
    links: List[LinkSpec] = field(default_factory=list)
    joints: List[JointSpec] = field(default_factory=list)


# ─── Specs des prototypes ─────────────────────────────────────────────────────

def spec_proto1_tripod() -> RobotSpec:
    """
    PROTO-1 : Tripode 3 pattes × 3 DOF = 9 DOF total.
    Corps central cylindrique, pattes réparties à 120°.
    Dimensions : corps Ø12cm × 4cm, fémur 8cm, tibia 10cm, pied 3cm.
    """
    spec = RobotSpec(
        name="proto1_tripod",
        body_radius=0.06,
        body_height=0.04,
        body_mass=0.3,
    )

    n_legs = 3
    femur_l, tibia_l, foot_l = 0.08, 0.10, 0.03
    femur_r, tibia_r, foot_r = 0.012, 0.010, 0.008
    femur_m, tibia_m, foot_m = 0.08, 0.06, 0.02

    for i in range(n_legs):
        angle_deg = i * 120
        angle_rad = math.radians(angle_deg)
        leg = f"leg{i+1}"
        attach_x = round(spec.body_radius * math.cos(angle_rad), 4)
        attach_y = round(spec.body_radius * math.sin(angle_rad), 4)
        rpy_z    = round(angle_rad, 4)

        # Links
        spec.links += [
            LinkSpec(f"{leg}_femur", femur_l, femur_r, femur_m, "0.2 0.7 0.2 1.0"),
            LinkSpec(f"{leg}_tibia", tibia_l, tibia_r, tibia_m, "0.1 0.5 0.1 1.0"),
            LinkSpec(f"{leg}_foot",  foot_l,  foot_r,  foot_m,  "0.8 0.3 0.1 1.0"),
        ]

        # Hip (coxa) joint — rotation autour de l'axe Z (abduction)
        spec.joints.append(JointSpec(
            name=f"{leg}_hip",
            parent="body",
            child=f"{leg}_femur",
            joint_type="revolute",
            axis_xyz="0 0 1",
            origin_xyz=f"{attach_x} {attach_y} 0",
            origin_rpy=f"0 0 {rpy_z}",
            lower=-0.5, upper=0.5,
        ))

        # Knee joint — rotation autour de l'axe Y (flexion/extension)
        spec.joints.append(JointSpec(
            name=f"{leg}_knee",
            parent=f"{leg}_femur",
            child=f"{leg}_tibia",
            joint_type="revolute",
            axis_xyz="0 1 0",
            origin_xyz=f"0 0 {-femur_l}",
            lower=-1.2, upper=0.2,
        ))

        # Ankle joint — rotation autour de l'axe Y
        spec.joints.append(JointSpec(
            name=f"{leg}_ankle",
            parent=f"{leg}_tibia",
            child=f"{leg}_foot",
            joint_type="revolute",
            axis_xyz="0 1 0",
            origin_xyz=f"0 0 {-tibia_l}",
            lower=-0.8, upper=0.8,
        ))

    return spec


def spec_proto2_quad() -> RobotSpec:
    """
    PROTO-2 : Quadrupède 4 pattes × 3 DOF = 12 DOF.
    Corps rectangulaire, pattes aux 4 coins.
    """
    spec = RobotSpec(
        name="proto2_quad",
        body_radius=0.0,   # non utilisé pour quad
        body_height=0.05,
        body_mass=0.5,
    )

    positions = {
        "fl": ( 0.10,  0.06),
        "fr": ( 0.10, -0.06),
        "rl": (-0.10,  0.06),
        "rr": (-0.10, -0.06),
    }
    femur_l, tibia_l, foot_l = 0.09, 0.11, 0.03

    for leg_id, (px, py) in positions.items():
        spec.links += [
            LinkSpec(f"{leg_id}_femur", femur_l, 0.012, 0.09, "0.2 0.6 0.9 1.0"),
            LinkSpec(f"{leg_id}_tibia", tibia_l, 0.010, 0.07, "0.1 0.4 0.8 1.0"),
            LinkSpec(f"{leg_id}_foot",  foot_l,  0.008, 0.02, "0.8 0.3 0.1 1.0"),
        ]
        spec.joints += [
            JointSpec(f"{leg_id}_hip",   "body", f"{leg_id}_femur", "revolute",
                      "0 1 0", f"{px} {py} 0", lower=-0.4, upper=0.4),
            JointSpec(f"{leg_id}_knee",  f"{leg_id}_femur", f"{leg_id}_tibia",
                      "revolute", "0 1 0", f"0 0 {-femur_l}", lower=-1.4, upper=0.1),
            JointSpec(f"{leg_id}_ankle", f"{leg_id}_tibia", f"{leg_id}_foot",
                      "revolute", "0 1 0", f"0 0 {-tibia_l}", lower=-0.8, upper=0.8),
        ]

    return spec


PROTO_SPECS = {
    "proto1_tripod": spec_proto1_tripod,
    "proto2_quad":   spec_proto2_quad,
}


# ─── Générateur URDF ──────────────────────────────────────────────────────────

class URDFGenerator:

    def generate(self, proto: str) -> str:
        if proto not in PROTO_SPECS:
            raise ValueError(f"Proto inconnu: {proto}. Disponibles: {list(PROTO_SPECS)}")
        spec = PROTO_SPECS[proto]()
        logger.info(f"[URDF] génération {proto} — {len(spec.links)} links, {len(spec.joints)} joints")
        return self._render(spec)

    def save(self, urdf: str, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(urdf, encoding="utf-8")
        logger.info(f"[URDF] sauvegardé : {p} ({len(urdf)} chars)")
        return p

    def _render(self, spec: RobotSpec) -> str:
        lines = [
            f'<?xml version="1.0"?>',
            f'<!-- Generated by Askio1 v2 — {datetime.now().strftime("%Y-%m-%d")} -->',
            f'<robot name="{spec.name}" xmlns:xacro="http://www.ros.org/wiki/xacro">',
            "",
            "  <!-- ── Matériaux ── -->",
            self._material("blue",  "0.2 0.4 0.8 1.0"),
            self._material("green", "0.2 0.7 0.2 1.0"),
            self._material("grey",  "0.5 0.5 0.5 1.0"),
            self._material("orange","0.8 0.4 0.1 1.0"),
            "",
            "  <!-- ── Corps central ── -->",
            self._body_link(spec),
            "",
            "  <!-- base_footprint pour Gazebo nav ── -->",
            self._footprint_link(),
            self._footprint_joint(spec),
            "",
            "  <!-- ── Pattes ── -->",
        ]

        for link in spec.links:
            lines.append(self._leg_link(link))

        lines.append("")
        lines.append("  <!-- ── Joints ── -->")

        for joint in spec.joints:
            lines.append(self._joint(joint))

        lines += ["", "</robot>", ""]
        return "\n".join(lines)

    def _material(self, name: str, rgba: str) -> str:
        return f'  <material name="{name}"><color rgba="{rgba}"/></material>'

    def _body_link(self, spec: RobotSpec) -> str:
        mass = spec.body_mass
        r    = spec.body_radius if spec.body_radius > 0 else 0.12
        h    = spec.body_height
        ixx  = round(mass * (3*r**2 + h**2) / 12, 6)
        return f"""  <link name="body">
    <visual>
      <geometry><cylinder radius="{r}" length="{h}"/></geometry>
      <material name="blue"/>
    </visual>
    <collision>
      <geometry><cylinder radius="{r}" length="{h}"/></geometry>
    </collision>
    <inertial>
      <mass value="{mass}"/>
      <inertia ixx="{ixx}" ixy="0" ixz="0" iyy="{ixx}" iyz="0" izz="{round(mass*r**2/2, 6)}"/>
    </inertial>
  </link>"""

    def _footprint_link(self) -> str:
        return '  <link name="base_footprint"/>'

    def _footprint_joint(self, spec: RobotSpec) -> str:
        h = spec.body_height / 2
        return f"""  <joint name="base_footprint_joint" type="fixed">
    <parent link="base_footprint"/>
    <child  link="body"/>
    <origin xyz="0 0 {round(h + 0.13, 3)}" rpy="0 0 0"/>
  </joint>"""

    def _leg_link(self, link: LinkSpec) -> str:
        r, l, m = link.radius, link.length, link.mass
        ixx = round(m * (3*r**2 + l**2) / 12, 6)
        return f"""  <link name="{link.name}">
    <visual>
      <origin xyz="0 0 {round(-l/2, 4)}" rpy="0 0 0"/>
      <geometry><cylinder radius="{r}" length="{l}"/></geometry>
      <material name="green"/>
    </visual>
    <collision>
      <origin xyz="0 0 {round(-l/2, 4)}" rpy="0 0 0"/>
      <geometry><cylinder radius="{r}" length="{l}"/></geometry>
    </collision>
    <inertial>
      <mass value="{m}"/>
      <inertia ixx="{ixx}" ixy="0" ixz="0" iyy="{ixx}" iyz="0" izz="{round(m*r**2/2, 6)}"/>
    </inertial>
  </link>"""

    def _joint(self, j: JointSpec) -> str:
        limit = ""
        if j.joint_type == "revolute":
            limit = f'\n    <limit lower="{j.lower}" upper="{j.upper}" effort="{j.effort}" velocity="{j.velocity}"/>'
        return f"""  <joint name="{j.name}" type="{j.joint_type}">
    <parent link="{j.parent}"/>
    <child  link="{j.child}"/>
    <origin xyz="{j.origin_xyz}" rpy="{j.origin_rpy}"/>
    <axis xyz="{j.axis_xyz}"/>{limit}
    <dynamics damping="0.01" friction="0.1"/>
  </joint>"""


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, sys
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Générateur URDF Askio1")
    parser.add_argument("--proto", default="proto1_tripod",
                        choices=list(PROTO_SPECS), help="Prototype à générer")
    parser.add_argument("--out",   default=None, help="Chemin de sortie (.urdf)")
    args = parser.parse_args()

    gen  = URDFGenerator()
    urdf = gen.generate(args.proto)

    if args.out:
        gen.save(urdf, args.out)
    else:
        out_path = Path(f"data/artifacts/simulation/{args.proto}.urdf")
        gen.save(urdf, out_path)
        print(f"Sauvegardé : {out_path}")
