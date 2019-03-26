#!/usr/bin/env python

# This work is licensed under the terms of the MIT license.
# For a copy, see <https://opensource.org/licenses/MIT>.

"""
Vehicle Manuevering In Opposite Direction:

Vehicle is passing another vehicle in a rural area, in daylight, under clear
weather conditions, at a non-junction and encroaches into another
vehicle traveling in the opposite direction.
"""

from Queue import Queue

import py_trees

from srunner.scenariomanager.atomic_scenario_behavior import *
from srunner.scenariomanager.atomic_scenario_criteria import *
from srunner.scenariomanager.carla_data_provider import CarlaDataProvider
from srunner.scenarios.basic_scenario import *
from srunner.scenarios.scenario_helper import get_waypoint_in_distance


MANEUVER_OPPOSITE_DIRECTION = [
    "ManeuverOppositeDirection"
]


class ManeuverOppositeDirection(BasicScenario):

    """
    "Vehicle Maneuvering In Opposite Direction" (Traffic Scenario 06)
    """

    category = "ManeuverOppositeDirection"
    timeout = 120

    def __init__(self, world, ego_vehicle, config, randomize=False, debug_mode=False, criteria_enable=True, obstacle_type='barrier'):
        """
        Setup all relevant parameters and create scenario
        obstacle_type -> flag to select type of leading obstacle. Values: vehicle, barrier
        """

        self._world = world
        self._map = CarlaDataProvider.get_map()
        self._first_vehicle_location = 50
        self._second_vehicle_location = self._first_vehicle_location + 40
        self._ego_vehicle_drive_distance = self._second_vehicle_location * 2
        self._start_distance = self._first_vehicle_location * 0.9
        self._opposite_speed = 30  # km/h
        self._reference_waypoint = self._map.get_waypoint(config.trigger_point.location)
        self._source_transform = None
        self._sink_location = None
        self._blackboard_queue_name = 'ManeuverOppositeDirection/actor_flow_queue'
        self._queue = Blackboard().set(self._blackboard_queue_name, Queue())
        self._obstacle_type = obstacle_type

        super(ManeuverOppositeDirection, self).__init__(
            "ManeuverOppositeDirection",
            ego_vehicle,
            config,
            world,
            debug_mode,
            criteria_enable=criteria_enable)

    def _initialize_actors(self, config):
        """
        Custom initialization
        """
        first_actor_waypoint, _ = get_waypoint_in_distance(self._reference_waypoint, self._first_vehicle_location)
        second_actor_waypoint, _ = get_waypoint_in_distance(self._reference_waypoint, self._second_vehicle_location)
        second_actor_waypoint = second_actor_waypoint.get_left_lane()

        first_actor_transform = carla.Transform(
            first_actor_waypoint.transform.location,
            first_actor_waypoint.transform.rotation)
        if self._obstacle_type == 'vehicle':
            first_actor_model = 'vehicle.nissan.micra'
        else:
            first_actor_transform.rotation.yaw += 90
            first_actor_model = 'static.prop.streetbarrier'
        first_actor = CarlaActorPool.request_new_actor(first_actor_model, first_actor_transform)
        first_actor.set_simulate_physics(True)
        second_actor = CarlaActorPool.request_new_actor('vehicle.audi.tt', second_actor_waypoint.transform)

        self.other_actors.append(first_actor)
        self.other_actors.append(second_actor)

        self._source_transform = second_actor_waypoint.transform
        sink_waypoint = second_actor_waypoint.next(1)[0]
        while not sink_waypoint.is_intersection:
            sink_waypoint = sink_waypoint.next(1)[0]
        self._sink_location = sink_waypoint.transform.location

    def _create_behavior(self):
        """
        The behavior tree returned by this method is as follows:
        The ego vehicle is trying to pass a leading vehicle in the same lane
        by moving onto the oncoming lane while another vehicle is moving in the
        opposite direction in the oncoming lane.
        """

        # Leaf nodes
        actor_source = ActorSource(
            self._world, ['vehicle.audi.tt', 'vehicle.tesla.model3', 'vehicle.nissan.micra'],
            self._source_transform, 20, self._blackboard_queue_name)
        actor_sink = ActorSink(self._world, self._sink_location, 10)
        ego_drive_distance = DriveDistance(self.ego_vehicle, self._ego_vehicle_drive_distance)
        waypoint_follower = WaypointFollower(
            self.other_actors[1], self._opposite_speed, blackboard_queue_name=self._blackboard_queue_name)
        opposite_start_trigger = InTriggerDistanceToVehicle(
            self.other_actors[0], self.ego_vehicle, self._start_distance)

        # Non-leaf nodes
        parallel_root = py_trees.composites.Parallel(policy=py_trees.common.ParallelPolicy.SUCCESS_ON_ONE)
        sequence = py_trees.composites.Sequence()

        # Building tree
        parallel_root.add_child(ego_drive_distance)
        parallel_root.add_child(sequence)
        parallel_root.add_child(actor_source)
        parallel_root.add_child(actor_sink)
        sequence.add_child(opposite_start_trigger)
        sequence.add_child(waypoint_follower)

        scenario_sequence = py_trees.composites.Sequence()
        scenario_sequence.add_child(ActorTransformSetter(self.other_actors[0], self._first_actor_transform))
        scenario_sequence.add_child(ActorTransformSetter(self.other_actors[1], self._second_actor_transform))
        scenario_sequence.add_child(parallel_root)
        scenario_sequence.add_child(ActorDestroy(self.other_actors[0]))
        scenario_sequence.add_child(ActorDestroy(self.other_actors[1]))

        return scenario_sequence

    def _create_test_criteria(self):
        """
        A list of all test criteria will be created that is later used
        in parallel behavior tree.
        """
        criteria = []

        collision_criterion = CollisionTest(self.ego_vehicle)
        criteria.append(collision_criterion)

        return criteria

    def __del__(self):
        """
        Remove all actors upon deletion
        """
        self.remove_all_actors()
