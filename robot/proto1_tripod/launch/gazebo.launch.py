"""
gazebo.launch.py — Launch file ROS2 pour PROTO-1 Tripode
=========================================================
Lance Gazebo avec le URDF du tripode + ros2_control + CPG controller.

Usage (ROS2 Humble installé) :
  ros2 launch robot/proto1_tripod/launch/gazebo.launch.py

Prérequis :
  sudo apt install ros-humble-gazebo-ros-pkgs ros-humble-ros2-control
  sudo apt install ros-humble-ros2-controllers
"""

import os
from pathlib import Path

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument, ExecuteProcess,
    IncludeLaunchDescription, TimerAction
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    # Chemins
    robot_dir  = Path(__file__).parent.parent
    urdf_path  = robot_dir / "urdf" / "proto1_tripod.urdf"
    world_path = robot_dir / "worlds" / "flat_ground.world"

    with open(urdf_path) as f:
        robot_description = f.read()

    # Arguments
    use_sim_time = LaunchConfiguration("use_sim_time", default="true")
    gui          = LaunchConfiguration("gui",          default="true")

    return LaunchDescription([
        DeclareLaunchArgument("use_sim_time", default_value="true"),
        DeclareLaunchArgument("gui",          default_value="true"),

        # ── Gazebo ──────────────────────────────────────────────────────────
        ExecuteProcess(
            cmd=["gazebo", "--verbose", str(world_path),
                 "-s", "libgazebo_ros_init.so",
                 "-s", "libgazebo_ros_factory.so"],
            output="screen",
        ),

        # ── Robot State Publisher ────────────────────────────────────────────
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            parameters=[{
                "robot_description": robot_description,
                "use_sim_time": use_sim_time,
            }],
            output="screen",
        ),

        # ── Spawn robot dans Gazebo ──────────────────────────────────────────
        TimerAction(period=3.0, actions=[
            Node(
                package="gazebo_ros",
                executable="spawn_entity.py",
                arguments=[
                    "-topic", "robot_description",
                    "-entity", "proto1_tripod",
                    "-x", "0", "-y", "0", "-z", "0.25",
                ],
                output="screen",
            ),
        ]),

        # ── Joint State Publisher (pour visualisation sans controller) ───────
        Node(
            package="joint_state_publisher",
            executable="joint_state_publisher",
            parameters=[{"use_sim_time": use_sim_time}],
        ),

        # ── CPG Controller node ──────────────────────────────────────────────
        TimerAction(period=5.0, actions=[
            Node(
                package="askio1_robot",
                executable="cpg_node",
                parameters=[{
                    "use_sim_time": use_sim_time,
                    "n_legs":  3,
                    "gait":    "tripod_wave",
                    "freq":    1.0,
                    "dt":      0.01,
                }],
                output="screen",
            ),
        ]),
    ])
