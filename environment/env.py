import os
import sys
import traci
import sumolib
from gym import Env
from gym import error, spaces, utils
from gym.utils import seeding
import traci
import traci.constants as tc
from scipy.misc import imread
from gym import spaces
from string import Template
import os, sys
import numpy as np
import math
import time
import re


from .traffic_signal import TrafficSignal


class SumoEnvironment(Env):

    KEEP = 0
    CHANGE = 1

    def __init__(self, conf_file, use_gui=False, num_seconds=20000, time_to_load_vehicles=0, delta_time=5):
        self._conf = conf_file
        if use_gui:
            self._sumo_binary = sumolib.checkBinary('sumo-gui')
        else:
            self._sumo_binary = sumolib.checkBinary('sumo')

        self.ts_ids = list()
        self.traffic_signals = dict()
        self.sim_max_time = num_seconds
        self.time_to_load_vehicles = time_to_load_vehicles
        self.delta_time = delta_time  # seconds on sumo at each step

        self.observation_space = spaces.Tuple((
            spaces.Discrete(2),   # Phase NS or EW
            spaces.Discrete(9),   # Duration of phase
            spaces.Discrete(10),  # NS stopped cars
            spaces.Discrete(10))  # EW stopped cars
        )
        self.action_space = spaces.Discrete(2)  # Keep or change

        self.radix_factors = [s.n for s in self.observation_space.spaces]

    def reset(self):
        sumo_cmd = [self._sumo_binary, '-c', self._conf]
        traci.start(sumo_cmd)
        self.ts_ids = traci.trafficlight.getIDList()
        for ts in self.ts_ids:
            self.traffic_signals[ts] = TrafficSignal(ts, self.delta_time)

        # Load vehicles
        for _ in range(self.time_to_load_vehicles):
            traci.simulationStep()

        return self._compute_observations()

    @property
    def sim_step(self):
        return traci.simulation.getCurrentTime()/1000

    def step(self, actions):
        # act
        self.apply_actions(actions)

        # run simulation for delta time
        for _ in range(self.delta_time):
            traci.simulationStep()

        # observe new state and reward
        observation = self._compute_observations()
        reward = self._compute_rewards()
        done = self.sim_step > self.sim_max_time

        info = {'step': self.sim_step, 'total_stopped': sum([self.traffic_signals[ts].ns_stopped[0] + self.traffic_signals[ts].ew_stopped[0] for ts in self.ts_ids])}

        return observation, reward, done, info

    def apply_actions(self, actions):
        for ts, action in actions.items():
            if action == self.KEEP:
                self.traffic_signals[ts].keep()
            elif action == self.CHANGE:
                self.traffic_signals[ts].change()

    def _compute_observations(self):
        observations = {}
        for ts in self.ts_ids:
            phase_id = self.traffic_signals[ts].phase / 2  # 0 -> 0 and 2 -> 1
            duration = self._discretize_duration(self.traffic_signals[ts].time_on_phase)
            ns_occupancy, ew_occupancy = self.traffic_signals[ts].get_occupancy()
            ns_occupancy, ew_occupancy = self._discretize_occupancy(ns_occupancy), self._discretize_occupancy(ew_occupancy)

            observations[ts] = self.radix_encode(phase_id, duration, ns_occupancy, ew_occupancy)
        return observations

    def _compute_rewards(self):
        rewards = {}
        for ts in self.ts_ids:
            ns_stopped, ew_stopped = self.traffic_signals[ts].get_stopped_vehicles_num()
            old_average = ((self.traffic_signals[ts].ns_stopped[1] + self.traffic_signals[ts].ew_stopped[1]) / 2)
            new_average = ((ns_stopped + ew_stopped) / 2)
            rewards[ts] = old_average - new_average
        return rewards

    def _discretize_occupancy(self, occupancy):
        if occupancy < 0.1:
            return 0
        elif occupancy < 0.2:
            return 1
        elif occupancy < 0.3:
            return 2
        elif occupancy < 0.4:
            return 3
        elif occupancy < 0.5:
            return 4
        elif occupancy < 0.6:
            return 5
        elif occupancy < 0.7:
            return 6
        elif occupancy < 0.8:
            return 7
        elif occupancy < 0.9:
            return 8
        else:
            return 9

    def _discretize_duration(self, duration):
        if duration <= 10:
            return 0
        elif duration < 15:
            return 1
        elif duration < 20:
            return 2
        elif duration < 25:
            return 3
        elif duration < 30:
            return 4
        elif duration < 35:
            return 5
        elif duration < 40:
            return 6
        elif duration < 45:
            return 7
        else:
            return 8

    def radix_encode(self, phase_id, duration, ns_stopped, ew_stopped):
        values = [phase_id, duration, ns_stopped, ew_stopped]
        res = 0
        for i in range(len(self.radix_factors)):
            res = res * self.radix_factors[i] + values[i]

        return int(res)

    def radix_decode(self, value):
        res = [0 for _ in range(len(self.radix_factors))]
        for i in reversed(range(4)):
            res[i] = value % self.radix_factors[i]
            value = value / self.radix_factors[i]
        return res

    def close(self):
        traci.close()
