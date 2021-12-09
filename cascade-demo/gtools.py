import numpy as np


def alt_calc(alt_dict):
    """
    Parameters
    ------------
    alt_dict: Dict{key drone_index (string): value altitude (float), ...}

    Returns
    -----------
    output_dict: Dict(key:drone_index (string), value: altitude (float))
    """
    # print("alt_dict=", alt_dict)
    site_elevation = 0  # 488
    alt_lims = np.array(
        [10, 100]
    )  # in meters - min return altitude above launch altitude
    alt_lims += site_elevation
    alt_step = 1  # in meters - the alt difference between return alts

    size = len(alt_dict)
    # Sorting dictionary by values and returning list of keys -----------------------------------------------------------------------------
    sorted_idx = sorted(alt_dict, key=alt_dict.get)

    # Calculating the mean of current alts -------------------------------------------------------------------------------
    mean = sum(alt_dict.values()) / size

    # Creating sorted return alts ------------------------------------------------------------------------------------------
    alts = np.arange(size) - (size - 1) / 2  # Makes an array centered around 0
    alts *= alt_step  # Increases to stepsize
    alts += mean  # Adds to mean

    # Checking minimum and maximum alt -----------------------------------------------------------------------------------------------
    if alts[0] < alt_lims[0]:
        difference = alt_lims[0] - alts[0]
        alts += difference  # Increase altitude so greater than min
    if alts[-1] > alt_lims[1]:
        difference = alts[-1] - alt_lims[1]
        alts -= difference  # Reduce altitude so less than max

    # Assigning alts to ordered index  -----------------------------------------------
    alt_return_dict = {}
    for i, idx in enumerate(sorted_idx):
        alt_return_dict[idx] = alts[i]

    return alt_return_dict


def proximity_check(swarm_telemetry):
    """
    Parameters
    ------------
    swarm_telemetry: Dict{key drone_index (string): AgentTelemetry (object), ...}

    Returns
    -----------
    output_dict: List[[drone_index (string), drone_index (string), distance],[...]
    """


def create_swarm_dict(real_swarm_size, sitl_swarm_size):
    # Create dict for real drones with IDs as keys
    real_dict = {}
    if real_swarm_size != 0:
        real_drone_ids = range(101, 101 + real_swarm_size)
        for i in real_drone_ids:
            real_dict["P" + str(i)] = None

    # Create dict for SITL drones with IDs as keys
    sitl_dict = {}
    if sitl_swarm_size != 0:
        sitl_drone_ids = range(1, 1 + sitl_swarm_size)
        for i in sitl_drone_ids:
            sitl_dict["S" + str(i).zfill(3)] = None

    swarm_dict = {**real_dict, **sitl_dict}
    return swarm_dict
