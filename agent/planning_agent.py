
#!/usr/bin/env python
from __future__ import print_function
import pybullet as p
import numpy as np
import time
import random
import math
import imageio
import matplotlib.pyplot as plt
import os
import shutil
import h5py
import imageio
from planning_pybullet.pybullet_tools.kuka_primitives import BodyPose, BodyConf, Command, get_grasp_gen, \
    get_ik_fn, get_free_motion_gen, get_holding_motion_gen
from planning_pybullet.pybullet_tools.utils import WorldSaver, enable_gravity, connect, dump_world, set_pose, \
    Pose, Point, Euler, set_default_camera, stable_z, \
    BLOCK_URDF, load_model, wait_for_user, disconnect, DRAKE_IIWA_URDF, user_input, update_state, disable_real_time,inverse_kinematics,end_effector_from_body,approach_from_grasp, get_joints, get_joint_positions


from planning_pybullet.pybullet_tools.utils import multiply, invert, get_pose, set_pose, get_movable_joints, \
    set_joint_positions, add_fixed_constraint_2, enable_real_time, disable_real_time, joint_controller, \
    enable_gravity, get_refine_fn, user_input, wait_for_duration, link_from_name, get_body_name, sample_placement, \
    end_effector_from_body, approach_from_grasp, plan_joint_motion, GraspInfo, Pose, INF, Point, \
    inverse_kinematics, pairwise_collision, remove_fixed_constraint, Attachment, get_sample_fn, \
    step_simulation, refine_path, plan_direct_joint_motion, get_joint_positions, dump_world, get_link_pose,control_joints

from planning_pybullet.pybullet_tools.kuka_primitives import BodyPath, Attach, Detach, ApplyForce
import pickle
import torch
from torch import nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import collections
from motion_planners.discrete import astar
import sys

from CuriousSamplePlanner.tasks.three_block_stack import ThreeBlocks

from CuriousSamplePlanner.tasks.ball_ramp import BallRamp
from CuriousSamplePlanner.tasks.pulley import PulleySeesaw
from CuriousSamplePlanner.tasks.bookshelf import BookShelf
from CuriousSamplePlanner.tasks.five_block_stack import FiveBlocks
from CuriousSamplePlanner.scripts.utils import *

from CuriousSamplePlanner.trainers.plan_graph import PlanGraph
from CuriousSamplePlanner.trainers.dataset import ExperienceReplayBuffer
import copy


class Link(ApplyForce):

    def __init__(self, link_point1):
        self.sphere = None
        self.link_point1 = link_point1

    def iterator(self):
        self.sphere = p.loadURDF("./models/yellow_sphere.urdf", self.link_point1)
        return []

class PlanningAgent():

    def __init__(self, environment):
        self.environment = environment
        self.links = []
        self.add_arm(self.environment.arm_size)

    def multistep_plan(self, plan):


        self.environment.set_state(plan[0].config)
        start_world = WorldSaver()


        for i in range(1, len(action)):

            saved_world = WorldSaver()
            macroaction_index = self.environment.get_macroaction_index(action[i])
            mask_start = len(self.environment.macroactions) + sum([self.environment.macroactions[macro_idx].num_params for macro_idx in range(macroaction_index)])
            mask_end = mask_start + self.environment.macroactions[macroaction_index].num_params
            macroaction = self.environment.macroactions[macroaction_index]
            macroaction.robot = self.robot
            macroaction.gmp = True
            macroaction.teleport = False
            aux, command = macroaction.execute(embedding = action[i][mask_start:mask_end])

            if(aux != None):
                self.links.append(aux)
            saved_world.restore()
            # Restore the state
            if(command is not None):
                self.execute(command)
                self.environment.run_until_stable(hook = self.hook, dt=0.01)
            commands.append(command)

        # # Remove all the links
        # for (link_object, link, link_transform, objobjlink) in self.links:
        #     p.removeBody(link_object.sphere)
        #     p.removeConstraint(link)
        #     p.removeConstraint(objobjlink)

        # self.links = []


        # self.environment.set_state(plan[0].config)
        # for command in commands:
        #     self.execute(command)
        #     self.environment.run_until_stable()

        for i in range(1000):
            p.stepSimulation()
            self.hook()
            time.sleep(0.01)



    def hook(self):
        for (link_object, link, link_transform, _) in self.links:
            if(link_object.sphere != None):
                lpos, lquat = p.getBasePositionAndOrientation(link)
                le = p.getEulerFromQuaternion(lquat)
                lpose = Pose(Point(*lpos), Euler(*le))
                set_pose(link_object.sphere, multiply(lpose, link_transform))

    def execute(self, command):
        command.refine(num_steps=10).execute(time_step=0.001, hook=self.hook)

    def hide_arm(self):
        p.removeBody(self.robot)

    def add_arm(self, arm_size):
        print(arm_size)
        arm_size=1.1
        self.robot = p.loadURDF(DRAKE_IIWA_URDF, useFixedBase=True, globalScaling=arm_size) # KUKA_IIWA_URDF | DRAKE_IIWA_URDF




