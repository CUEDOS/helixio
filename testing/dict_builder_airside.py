import time
from math import cos, sin, sqrt
import asyncio
from mavsdk import System
from mavsdk.offboard import OffboardError, VelocityNedYaw
import pymap3d as pm
import paho.mqtt.client as mqtt

CONST_DRONE_ID = "P101"
CONST_SWARM_SIZE = 8

# below are reference GPS coordinates used as the origin of the NED coordinate system
CONST_REF_LAT = 53.473489655102014
CONST_REF_LON = -2.2354534026550343
CONST_REF_ALT = 0


class PosVelNED:
    position = [0, 0, 0]
    velocity = [0, 0, 0]


my_telemetry = PosVelNED()

# Create dict of PosVelNED objects with drone identifier e.g. P101 as the keys
drone_ids = range(101, 101 + CONST_SWARM_SIZE)
swarm_telemetry = {}
for i in drone_ids:
    swarm_telemetry["P" + str(i)] = PosVelNED()

client = mqtt.Client()
# client.connect("localhost", 1883, 60)  # change localhost to IP of broker

# run function (main code)
async def run():

    drone = System()
    await drone.connect(system_address="udp://:14540")
    print("Waiting for drone to connect...")
    async for state in drone.core.connection_state():
        if state.is_connected:
            print(f"Drone discovered!")
            break

    print("-- Arming")
    await drone.action.arm()

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
        await drone.action.disarm()
        return
    # Start background task
    asyncio.ensure_future(dict_builder())
    asyncio.ensure_future(get_position(drone))
    asyncio.ensure_future(get_velocity(drone))
    # End of Init the drone
    target_pos = [0, 0, 0]
    target_vel = [0, 0, 0]
    pos_error = [0, 0, 0]
    kp = 2
    ki = 1
    dt = 0.1  # duration of each loop
    max_speed = 5  # maximum magnitude of the speed vector
    # take off the quadrotor
    await drone.offboard.set_velocity_ned(VelocityNedYaw(0.0, 0.0, -2.0, 0.0))
    await asyncio.sleep(5)

    mission_start_time = time.time()  # start time of the mission
    # Endless loop (Mission)
    while True:
        loop_start_time = time.time()
        # print(my_telemetry.position)
        client.publish(
            CONST_DRONE_ID + "/telemetry/position", str(my_telemetry.position)
        )
        client.publish(
            CONST_DRONE_ID + "/telemetry/velocity", str(my_telemetry.velocity)
        )

        # Creating desired path
        t = time.time() - mission_start_time  # current time of the mission

        target_pos = [5 * sin(0.5 * t), 5 * cos(0.5 * t), -20]
        target_vel = [0.5 * 5 * cos(0.5 * t), 0.5 * -5 * sin(0.5 * t), 0]

        output_vel, pos_error = position_to_velocity(
            target_pos, target_vel, pos_error, kp, ki, max_speed, dt
        )

        # Sending the target velocities to the quadrotor
        await drone.offboard.set_velocity_ned(
            VelocityNedYaw(output_vel[0], output_vel[1], output_vel[2], 0.0)
        )

        # Checking frequency of the loop
        await asyncio.sleep(
            0.1 - (time.time() - loop_start_time)
        )  # to make while 1 work at 10 Hz
        # print("loop duration=", (time.time() - loop_start_time))
        print(swarm_telemetry)
    # End of Endless loop


# End of run function (main code)

# runs in background and upates state class with latest telemetry
async def get_position(drone):
    async for position in drone.telemetry.position():
        my_telemetry.position = pm.geodetic2ned(
            position.latitude_deg,
            position.longitude_deg,
            position.absolute_altitude_m,
            CONST_REF_LAT,
            CONST_REF_LON,
            CONST_REF_ALT,
        )


async def get_velocity(drone):
    async for position_velocity_ned in drone.telemetry.position_velocity_ned():
        my_telemetry.velocity = [
            position_velocity_ned.velocity.north_m_s,
            position_velocity_ned.velocity.east_m_s,
            position_velocity_ned.velocity.down_m_s,
        ]


async def dict_builder():
    client.message_callback_add("+/telemetry/position", on_message_position)
    client.message_callback_add("+/telemetry/velocity", on_message_velocity)
    client.connect_async("localhost", 1883, 60)  # change localhost to IP of broker
    client.on_connect = on_connect
    client.loop_start()


def position_to_velocity(target_pos, target_vel, pos_error, kp, ki, max_speed, dt):
    # PID controller
    prev_error = [0, 0, 0]
    integ = [0, 0, 0]
    output_vel = [0, 0, 0]
    for i in range(0, 3):
        prev_error[i] = pos_error[i]
        pos_error[i] = target_pos[i] - my_telemetry.position[i]
        integ[i] = ((pos_error[i] + prev_error[i]) / 2) * dt + integ[i]
        if integ[i] >= 1:  # limiting the accumulator of integral term
            integ[i] = 1
        if integ[i] <= -1:
            integ[i] = -1

        output_vel[i] = kp * (pos_error[i]) + ki * integ[i] + target_vel[i]

    # limiting and normalizing the speed of the drone
    v = sqrt(output_vel[0] ** 2 + output_vel[1] ** 2 + output_vel[2] ** 2)
    norm_factor = 1
    if v > max_speed:
        norm_factor = max_speed / v
        for i in range(0, 3):
            output_vel[i] *= norm_factor

    return output_vel, pos_error


def on_connect(client, userdata, flags, rc):
    print("MQTT connected to broker with result code " + str(rc))
    client.subscribe("+/telemetry/+")


def on_message_position(mosq, obj, msg):
    # Remove none numeric parts of string and then split into north east and down
    received_string = msg.payload.decode().strip("()")
    string_list = received_string.split(", ")
    position = [float(i) for i in string_list]
    swarm_telemetry[msg.topic[0:4]].position = position


def on_message_velocity(mosq, obj, msg):
    # Remove none numeric parts of string and then split into north east and down
    received_string = msg.payload.decode().strip("[]")
    string_list = received_string.split(", ")
    velocity = [float(i) for i in string_list]
    swarm_telemetry[msg.topic[0:4]].velocity = velocity


if __name__ == "__main__":
    # Start the main function
    asyncio.ensure_future(run())

    # Runs the event loop until the program is canceled with e.g. CTRL-C
    asyncio.get_event_loop().run_forever()
