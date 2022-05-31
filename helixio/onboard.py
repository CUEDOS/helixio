import sys
import time
import json
import logging
import asyncio
import typing

import flocking
from mavsdk import System
from mavsdk.action import ActionError
from mavsdk.offboard import OffboardError, VelocityNedYaw
import pymap3d as pm
from communication import DroneCommunication
from data_structures import AgentTelemetry
import math
import numpy as np


def index_checker(input_index, length) -> int:
    if input_index >= length:
        return int(input_index % length)
    return input_index


class Experiment:
    def __init__(self, drone) -> None:
        self.ready_flag = False
        self.drone = drone
        self.least_distance = 2  # minimum allowed distance between two agents
        # Set up corridor variables
        self.points = [[]]
        self.current_path=0 # number of curent path the drone should follow, it should be gotten from GCS like initial prestart points-----!!!!!
        self.lane_radius = [] # should be a list ------!!!

        # Sensible defaults for gains
        self.k_migration = 1
        self.k_lane_cohesion = 2
        # self.k_rotation = 0.1
        self.k_rotation = 0.5
        self.k_separation = 2

        self.directions = [[]]
        self.current_index = 0
        self.target_point = np.array([0, 0, 0])
        self.target_direction = np.array([1, 1, 1])

    def set_corridor(self, corridor_json):
        corridor = json.loads(corridor_json)
        self.lane_radius = corridor["corridor_radius"]
        self.points = corridor["corridor_points"]
        self.length = [len(self.points[j]) for j in range(len(self.points))] # j is the number of a path
        self.pass_permission=[1 for j in range(len(self.points))] # the permission to go to the next path
        self.create_directions()
        self.initial_nearest_point()
        self.create_adjacent_points()
        self.ready_flag = True
        print("ready")

    def create_directions(self) -> None:
        for j in range(len(self.points)):
            for i in range(len(self.points[j])):
                # All points must be converted to np arrays
                self.points[j][i] = np.array(self.points[j][i])

                if i == len(self.points[j]) - 1:
                    self.directions.append(
                        (self.points[j][0] - self.points[j][i])
                        / np.linalg.norm(self.points [j][0] - self.points[j][i])
                    )
                else:
                    self.directions.append(
                        (self.points[j][i + 1] - self.points[j][i])
                        / np.linalg.norm(self.points[j][i + 1] - self.points[j][i])
                    )
    def create_adjacent_points(self) -> None: 
        self.adjacent_points=[]
        for j in range(len(self.points)-1):
            self.adjacent_points.append({})
            for i in range(len(self.points[j])):
                for k in range(len(self.points[j+1])):
                    distance=np.linalg.norm(self.points[j][i]-self.points[j][k])
                    if (distance<= self.lane_radius[j]+self.lane_radius[j+1] and np.dot(self.directions[j][i], self.directions[j][k])==1):
                        pass_vector=self.points[j][i]-self.points[j+1][k]
                        pass_vector=pass_vector/np.linalg.norm(pass_vector)
                        self.adjacent_points[j].update({i:[k,pass_vector]}) # jth dictionary is {adj. point of path j: [adj. point of j+1, vector from adj. point of path j to adj. point of j+1]}

    def initial_nearest_point(self) -> None:
        lnitial_least_distance = math.inf
        for i in range(len(self.points[self.current_path])):
            range_to_point_i = np.linalg.norm(
                np.array(agent.my_telem.position_ned) - self.points[self.current_path][i]
            )
            if range_to_point_i <= lnitial_least_distance:
                lnitial_least_distance = range_to_point_i
                self.current_index= i

    def Swithch(self):
        self.pass_permission[self.current_path]=0 # the agent is not allowed to get back to previous path anymore
        self.current_index=self.adjacent_points[self.current_path][self.current_index][0] # now current index is a point of the next path
        self.current_path+=1
        self.target_point = self.points[self.current_path][self.current_index]
        self.target_direction = self.directions[self.current_path][self.current_index]

    def path_following(
        self, drone_id, swarm_telem, my_telem, max_speed, time_step, max_accel
    ):
        self.target_point = self.points[self.current_path][self.current_index]
        self.target_direction = self.directions[self.current_path][self.current_index]
        if ((self.current_index in self.adjacent_points[self.current_path]) and self.pass_permission[self.current_path]==1):
            pass_vector=self.adjacent_points[self.current_path][self.current_index][1]
            lane_cohesion_position_error = self.target_point-np.array(agent.my_telem.position_ned)
            lane_cohesion_position_error -= ( np.dot(lane_cohesion_position_error, self.target_direction)* self.target_direction)
            cos_of_angle=np.dot(pass_vector, lane_cohesion_position_error)/(np.linalg.norm(pass_vector)*np.inalg.norm(lane_cohesion_position_error))
            if (cos_of_angle>=0.9):
                self.Switch()
        # Finding the next bigger Index ----------
        range_to_next = (
            np.array(my_telem.position_ned)
            - self.points[self.current_path][index_checker(self.current_index + 1, self.length[self.current_path])]
        )

        if (
            np.dot(range_to_next, self.directions[self.current_path][self.current_index]) > 0
        ):  # drone has passed the point next to current one
            self.current_index = index_checker(self.current_index + 1, self.length[self.current_path])
            self.target_point = self.points[self.current_path][self.current_index]
            self.target_direction = self.directions[self.current_path][self.current_index]
            iterator = 0
            dot_fartherpoints = 0
            while dot_fartherpoints >= 0:  # Searching for farther points
                iterator += 1
                farther_point = index_checker(
                    self.current_index + iterator, self.length[self.current_path]
                )
                range_to_farther_point = (
                    np.array(my_telem.position_ned) - self.points[self.current_path][farther_point]
                )
                dot_fartherpoints = np.dot(
                    range_to_farther_point, self.directions[self.current_path][farther_point - 1]
                )

            self.current_index = (
                farther_point - 1
            )  # farther_point here has negative dot product
            self.target_point = self.points[self.current_path][self.current_index]
            self.target_direction = self.directions[self.current_path][self.current_index]

        # Calculating migration velocity (normalized)---------------------
        limit_v_migration = 1
        v_migration = self.target_direction / np.linalg.norm(self.target_direction)
        if np.linalg.norm(v_migration) > limit_v_migration:
            v_migration = v_migration * limit_v_migration / np.linalg.norm(v_migration)

        # Calculating lane Cohesion Velocity ---------------
        limit_v_lane_cohesion = 1
        lane_cohesion_position_error = self.target_point - np.array(
            agent.my_telem.position_ned
        )
        lane_cohesion_position_error -= (
            np.dot(lane_cohesion_position_error, self.target_direction)
            * self.target_direction
        )
        lane_cohesion_position_error_magnitude = np.linalg.norm(
            lane_cohesion_position_error
        )

        if np.linalg.norm(lane_cohesion_position_error) != 0:
            v_lane_cohesion = (
                (lane_cohesion_position_error_magnitude - self.lane_radius)
                * lane_cohesion_position_error
                / np.linalg.norm(lane_cohesion_position_error)
            )
        else:
            v_lane_cohesion = np.array([0.01, 0.01, 0.01])

        if np.linalg.norm(v_lane_cohesion) > limit_v_lane_cohesion:
            v_lane_cohesion = (
                v_lane_cohesion
                * limit_v_lane_cohesion
                / np.linalg.norm(v_lane_cohesion)
            )

        # Calculating v_rotation (normalized)---------------------
        limit_v_rotation = 1
        if lane_cohesion_position_error_magnitude < self.lane_radius:
            v_rotation_magnitude = (
                lane_cohesion_position_error_magnitude / self.lane_radius
            )
        else:
            v_rotation_magnitude = (
                self.lane_radius / lane_cohesion_position_error_magnitude
            )
        cross_prod = np.cross(lane_cohesion_position_error, self.target_direction)
        if np.linalg.norm(cross_prod) != 0:
            v_rotation = v_rotation_magnitude * cross_prod / np.linalg.norm(cross_prod)
        else:
            v_rotation = np.array[0, 0, 0]

        if np.linalg.norm(v_rotation) > limit_v_rotation:
            v_rotation = v_rotation * limit_v_rotation / np.linalg.norm(v_rotation)

        # Calculating v_separation (normalized) -----------------------------
        limit_v_separation = 5
        r_conflict = 5
        r_collision = 2.5
        v_separation = np.array([0, 0, 0])
        for key in swarm_telem:
            if key == drone_id:
                continue
            p = np.array(swarm_telem[key].position_ned)
            x = np.array(my_telem.position_ned) - p
            d = np.linalg.norm(x)
            if self.least_distance > d:
                self.least_distance = d
            if d <= r_conflict and d > r_collision and d != 0:
                v_separation = v_separation + (
                    (x / d) * (r_conflict - d / r_conflict - r_collision)
                )
            if d <= r_collision and d != 0:
                v_separation = v_separation + 1 * (x / d)
            if np.linalg.norm(v_separation) > limit_v_separation:
                v_separation = (
                    v_separation * limit_v_separation / np.linalg.norm(v_separation)
                )

        desired_vel = (
            self.k_lane_cohesion * v_lane_cohesion
            + self.k_migration * v_migration
            + self.k_rotation * v_rotation
            + self.k_separation * v_separation
        )

        # NOTE maybe add lane cohesion as well so we point the right way when coming from far away
        yaw = flocking.get_desired_yaw(v_migration[0], v_migration[1])

        output_vel = flocking.check_velocity(
            desired_vel, my_telem, max_speed, yaw, time_step, max_accel
        )
        return output_vel


# Class containing all methods for the drones.
class Agent:
    def __init__(self):
        # Open the json file where the config parameters are stored and read them
        print("opening json file")
        with open(CONST_JSON_PATH, "r") as f:
            parameters = json.load(f)
        self.load_parameters(parameters)

        self.my_telem = AgentTelemetry()
        self.return_alt = 10
        if self.logging == True:
            self.logger = setup_logger(self.id)
        print("setup done")

    async def run(self):
        self.drone = System(mavsdk_server_address="localhost", port=self.port)
        await self.drone.connect()
        print("Waiting for drone to connect...")
        async for state in self.drone.core.connection_state():
            if state.is_connected:
                print(f"Drone discovered!")
                break

        self.experiment = Experiment(self.drone)

        self.comms = DroneCommunication(
            self,
            self.broker_ip,
            self.id,
            self.experiment,
        )
        asyncio.ensure_future(self.comms.run_comms())

        await asyncio.sleep(1)
        asyncio.ensure_future(self.get_position(self.drone))
        asyncio.ensure_future(self.get_heading(self.drone))
        asyncio.ensure_future(self.get_velocity(self.drone))
        asyncio.ensure_future(self.get_arm_status(self.drone))
        asyncio.ensure_future(self.get_battery_level(self.drone))
        asyncio.ensure_future(self.get_flight_mode(self.drone))

        # Put command callback functions in a dict with command as key
        command_functions = {
            "arm": self.arm,
            "takeoff": self.takeoff,
            "Simple Flocking": self.simple_flocking,
            "Experiment": self.run_experiment,
            "Migration Test": self.migration_test,
            "hold": self.hold,
            "return": self.return_to_home,
            "land": self.land,
            "disconnect": self.on_disconnect,
        }

        # Bind the callbacks
        self.comms.bind_command_functions(command_functions, event_loop)

    async def on_disconnect(self):
        print("connection lost, timeout in 5s")
        await asyncio.sleep(5)
        if self.comms.connected == False:
            # await self.catch_action_error(self.drone.action.hold())
            print("connection lost: logging")
            self.logger.warning("connection lost")

    def load_parameters(self, parameters):
        # takes dict of parameters and loads them into variables
        self.id: str = parameters["id"]
        self.broker_ip: str = parameters["broker_ip"]
        self.port: int = parameters["port"]
        self.logging: bool = parameters["logging"]
        self.max_speed: int = parameters["max_speed"]
        self.ref_lat: float = parameters["ref_lat"]
        self.ref_lon: float = parameters["ref_lon"]
        self.ref_alt: float = parameters["ref_alt"]

    def update_parameter(self, new_parameters_json):

        new_parameters = json.loads(new_parameters_json)

        # load old parameters and insert new ones
        with open(CONST_JSON_PATH, "r") as f:
            parameters = json.load(f)

        for key in new_parameters.keys():
            parameters[key] = new_parameters[key]
        # write new parameters to file
        with open(CONST_JSON_PATH, "w") as f:
            json.dump(parameters, f)

        self.load_parameters(parameters)

    async def arm(self):
        print("ARMING")
        self.logger.info("arming")

        try:
            await self.drone.action.arm()
            self.home_lat = self.my_telem.geodetic[0]
            self.home_long = self.my_telem.geodetic[1]
        except ActionError as error:
            self.report_error(error._result.result_str)

    async def takeoff(self):
        print("Taking Off")
        self.logger.info("taking-off")
        try:
            await self.drone.action.set_takeoff_altitude(20)
            await self.drone.action.takeoff()
        except ActionError as error:
            self.report_error(error._result.result_str)

    async def hold(self):
        print("Hold")
        self.logger.info("holding")
        try:
            await self.drone.action.hold()
        except ActionError as error:
            self.report_error(error._result.result_str)

    async def land(self):
        print("Landing")
        self.logger.info("landing")
        try:
            await self.drone.action.land()
        except ActionError as error:
            self.report_error(error._result.result_str)

    async def start_offboard(self, drone):
        print("-- Setting initial setpoint")
        await drone.offboard.set_velocity_ned(VelocityNedYaw(0.0, 0.0, 0.0, 0.0))
        print("-- Starting offboard")
        try:
            await drone.offboard.start()
        except OffboardError as error:
            print(
                f"Starting offboard mode failed with error code: \
                {error._result.result}"
            )
            print("-- Disarming")
            self.report_error(error._result.result_str)
            self.logger.error("Offboard failed to start: ", error._result.result_str)
            await drone.action.hold()
            print("could not start offboard")
            return

    async def run_experiment(self):
        print("running experiment")
        await self.start_offboard(self.drone)

        # End of Init the drone
        offboard_loop_duration = 0.1  # duration of each loop

        # Loop in which the velocity command outputs are generated
        while (
            self.comms.current_command == "Experiment"
            and self.experiment.ready_flag == True
        ):
            offboard_loop_start_time = time.time()

            await self.drone.offboard.set_velocity_ned(
                self.experiment.path_following(
                    self.id,
                    self.comms.swarm_telemetry,
                    self.my_telem,
                    self.max_speed,
                    offboard_loop_duration,
                    5,
                )
            )

            # Checking frequency of the loop
            await asyncio.sleep(
                offboard_loop_duration - (time.time() - offboard_loop_start_time)
            )

    async def simple_flocking(self):
        # pre-swarming process
        swarming_start_lat = self.my_telem.geodetic[0]
        swarming_start_long = self.my_telem.geodetic[1]

        print("Preparing Swarming")
        await self.drone.action.hold()
        await asyncio.sleep(1)

        print("START ALTITUDE:")
        print(self.comms.return_alt)

        try:
            await self.drone.action.goto_location(
                swarming_start_lat, swarming_start_long, self.comms.return_alt, 0
            )
        except ActionError as error:
            self.report_error(error._result.result_str)

        while abs(self.my_telem.geodetic[2] - self.comms.return_alt) > 0.5:
            await asyncio.sleep(1)

        try:
            await self.drone.action.goto_location(
                self.mission_lat, self.mission_long, self.comms.return_alt, 0
            )
        except ActionError as error:
            self.report_error(error._result.result_str)

        await self.start_offboard(self.drone)

        # End of Init the drone
        offboard_loop_duration = 0.1  # duration of each loop

        exp = Experiment(self.drone)

        # Catch points, direction

        # Then calculate nearest point

        # Loop in which the velocity command outputs are generated
        while self.comms.current_command == "Simple Flocking":
            offboard_loop_start_time = time.time()

            output_vel = flocking.simple_flocking(
                self.id,
                self.comms.swarm_telemetry,
                self.my_telem,
                offboard_loop_duration,
                5,
            )

            # Sending the target velocities to the quadrotor
            await self.drone.offboard.set_velocity_ned(
                flocking.check_velocity(
                    output_vel,
                    self.my_telem,
                    self.max_speed,
                    0.0,
                    offboard_loop_duration,
                    5,
                )
            )

            # logging the position of each drone in the swarm that this drone has
            for key in self.comms.swarm_telemetry.keys():
                self.logger.info(
                    key + ": " + str(self.comms.swarm_telemetry[key].position_ned)
                )

            # logging the velocity commands sent to the pixhawk
            self.logger.info(
                str(
                    flocking.check_velocity(
                        output_vel,
                        self.my_telem,
                        self.max_speed,
                        0.0,
                        offboard_loop_duration,
                        5,
                    )
                )
            )
            # Checking frequency of the loop
            await asyncio.sleep(
                offboard_loop_duration - (time.time() - offboard_loop_start_time)
            )

    async def single_torus(self):
        await self.start_offboard(self.drone)

        # End of Init the drone
        offboard_loop_duration = 0.1  # duration of each loop

        # Loop in which the velocity command outputs are generated
        while self.comms.current_command == "Single Torus":
            offboard_loop_start_time = time.time()

            output_vel = flocking.single_torus_swarming(
                self.id,
                self.comms.swarm_telemetry,
                self.my_telem,
                offboard_loop_duration,
                5,
            )

            # Sending the target velocities to the quadrotor
            await self.drone.offboard.set_velocity_ned(
                flocking.check_velocity(
                    output_vel,
                    self.my_telem,
                    self.max_speed,
                    0.0,
                    offboard_loop_duration,
                    5,
                )
            )

            # logging the position of each drone in the swarm that this drone has
            for key in self.comms.swarm_telemetry.keys():
                self.logger.info(
                    key + ": " + str(self.comms.swarm_telemetry[key].position_ned)
                )

            # logging the velocity commands sent to the pixhawk
            self.logger.info(
                str(
                    flocking.check_velocity(
                        output_vel,
                        self.my_telem,
                        self.max_speed,
                        0.0,
                        offboard_loop_duration,
                        5,
                    )
                )
            )
            # Checking frequency of the loop
            await asyncio.sleep(
                offboard_loop_duration - (time.time() - offboard_loop_start_time)
            )

    async def migration_test(self):
        await self.start_offboard(self.drone)

        # End of Init the drone
        offboard_loop_duration = 0.1  # duration of each loop

        await asyncio.sleep(2)
        # Endless loop (Mission)
        Migrated = False
        while self.comms.current_command == "Migration Test":
            print("getting new point to migrate to")
            desired_pos = flocking.migration_test(Migrated)
            print(desired_pos)
            while self.comms.current_command == "Migration Test" and (
                abs(self.my_telem.position_ned[0] - desired_pos[0]) > 1
                or abs(self.my_telem.position_ned[1] - desired_pos[1]) > 1
                or abs(self.my_telem.position_ned[2] - desired_pos[2]) > 1
            ):
                offboard_loop_start_time = time.time()

                flocking_vel = flocking.simple_flocking(
                    self.id,
                    self.comms.swarm_telemetry,
                    self.my_telem,
                    offboard_loop_duration,
                    1,
                )

                migration_vel, yaw = flocking.velocity_to_point(
                    self.my_telem, desired_pos
                )

                output_vel = flocking_vel + migration_vel

                # Sending the target velocities to the quadrotor
                await self.drone.offboard.set_velocity_ned(
                    flocking.check_velocity(
                        output_vel,
                        self.my_telem,
                        self.max_speed,
                        yaw,
                        offboard_loop_duration,
                        2,
                    )
                )

                # Checking frequency of the loop
                await asyncio.sleep(
                    offboard_loop_duration - (time.time() - offboard_loop_start_time)
                )
            Migrated = not Migrated

    async def return_to_home(self):
        rtl_start_lat = self.my_telem.geodetic[0]
        rtl_start_long = self.my_telem.geodetic[1]

        print("Returning to home")
        await self.drone.action.hold()
        await asyncio.sleep(1)

        print("RETURN ALTITUDE:")
        print(self.comms.return_alt)

        try:
            await self.drone.action.goto_location(
                rtl_start_lat, rtl_start_long, self.comms.return_alt, 0
            )
        except ActionError as error:
            self.report_error(error._result.result_str)

        while abs(self.my_telem.geodetic[2] - self.comms.return_alt) > 0.5:
            await asyncio.sleep(1)

        try:
            await self.drone.action.goto_location(
                self.home_lat, self.home_long, self.comms.return_alt, 0
            )
        except ActionError as error:
            self.report_error(error._result.result_str)

    # runs in background and upates state class with latest telemetry
    async def get_position(self, drone):
        # set the rate of telemetry updates to 10Hz
        await drone.telemetry.set_rate_position(10)
        async for position in drone.telemetry.position():

            self.my_telem.geodetic = (
                position.latitude_deg,
                position.longitude_deg,
                position.absolute_altitude_m,
            )

            self.my_telem.position_ned = pm.geodetic2ned(
                position.latitude_deg,
                position.longitude_deg,
                position.absolute_altitude_m,
                self.ref_lat,
                self.ref_lon,
                self.ref_alt,
            )

            self.comms.client.publish(
                self.id + "/telemetry/position_ned",
                str(self.my_telem.position_ned).strip("()"),
            )

            self.comms.client.publish(
                self.id + "/telemetry/geodetic",
                str(self.my_telem.geodetic).strip("()"),
            )

    async def get_heading(self, drone):
        # set the rate of telemetry updates to 10Hz
        # await drone.telemetry.set_rate_heading(10)
        async for heading in drone.telemetry.heading():

            self.my_telem.heading = heading

            self.comms.client.publish(
                self.id + "/telemetry/heading",
                str(self.my_telem.heading.heading_deg).strip("()"),
            )

    async def get_velocity(self, drone):
        # set the rate of telemetry updates to 10Hz
        await drone.telemetry.set_rate_position_velocity_ned(10)
        async for position_velocity_ned in drone.telemetry.position_velocity_ned():
            # changed from list to tuple so formatting for all messages is the same
            self.my_telem.velocity_ned = (
                position_velocity_ned.velocity.north_m_s,
                position_velocity_ned.velocity.east_m_s,
                position_velocity_ned.velocity.down_m_s,
            )
            self.comms.client.publish(
                self.id + "/telemetry/velocity_ned",
                str(self.my_telem.velocity_ned).strip("()"),
            )

    async def get_arm_status(self, drone):
        async for arm_status in drone.telemetry.armed():

            if arm_status != self.my_telem.arm_status:
                self.my_telem.arm_status = arm_status
                self.comms.client.publish(
                    self.id + "/telemetry/arm_status",
                    str(self.my_telem.arm_status),
                )

    async def get_battery_level(self, drone):
        await drone.telemetry.set_rate_battery(0.1)
        async for battery_level in drone.telemetry.battery():
            self.comms.client.publish(
                self.id + "/battery_level",
                str(round(battery_level.remaining_percent * 100)),
            )

    async def get_flight_mode(self, drone):
        previous_flight_mode = "NONE"
        async for flight_mode in drone.telemetry.flight_mode():
            if flight_mode != previous_flight_mode:
                previous_flight_mode = flight_mode
                print(flight_mode)
                self.comms.client.publish(
                    self.id + "/flight_mode", str(flight_mode), qos=2
                )

    def report_error(self, error):
        print("Action Failed: ", error)
        self.logger.error("Action Failed: ", error)
        self.comms.client.publish("errors", self.id + ": " + error)


def setup_logger(id):
    log_format = "%(levelname)s %(asctime)s - %(message)s"
    log_date = time.strftime("%d-%m-%y_%H-%M")

    logging.basicConfig(
        filename="logs/" + id + "_" + log_date + ".log",
        filemode="w",
        format=log_format,
        level=logging.INFO,
    )

    logger = logging.getLogger()
    return logger


if __name__ == "__main__":

    # Takes command line arguments
    # CONST_DRONE_ID = str(sys.argv[1])
    # CONST_REAL_SWARM_SIZE = int(sys.argv[2])
    # CONST_SITL_SWARM_SIZE = int(sys.argv[3])
    # CONST_SWARM_SIZE = CONST_REAL_SWARM_SIZE + CONST_SITL_SWARM_SIZE
    # CONST_PORT = int(sys.argv[4])
    # CONST_LOGGING = bool(
    #    sys.argv[5]
    # )  # 5th argument should be empty for no logging and 'L' for logging enabled
    # CONST_MAX_SPEED = 5

    # below are reference GPS coordinates used as the origin of the NED coordinate system

    # For Zurich
    # CONST_REF_LAT = 47.39796
    # CONST_REF_LON = 8.5443076
    # CONST_REF_ALT = 488

    # For Baylands
    # CONST_REF_LAT = 37.413534
    # CONST_REF_LON = -121.996561
    # CONST_REF_ALT = 1.3

    # For Hough End
    # CONST_REF_LAT = 53.43578053111544
    # CONST_REF_LON = -2.250343561172483
    # CONST_REF_ALT = 31

    CONST_JSON_PATH = str(sys.argv[1])
    # Start the main function
    agent = Agent()
    asyncio.ensure_future(agent.run())
    # Runs the event loop until the program is canceled with e.g. CTRL-C
    event_loop = asyncio.get_event_loop()
    event_loop.run_forever()
