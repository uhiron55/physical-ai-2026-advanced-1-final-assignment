features = {
    "observation.images.front": {
        "dtype": "image",
        "shape": (3, 240, 320),
        "names": ["channels", "height", "width"],
    },
    "observation.state": {
        "dtype": "float32",
        "shape": (5,),
        "names": [
            "crane_plus_joint1",
            "crane_plus_joint2",
            "crane_plus_joint4",
            "crane_plus_joint3",
            "crane_plus_joint_hand",
        ],
    },
    "action": {
        "dtype": "float32",
        "shape": (5,),
        "names": [
            "crane_plus_joint1",
            "crane_plus_joint2",
            "crane_plus_joint4",
            "crane_plus_joint3",
            "crane_plus_joint_hand",
        ],
    },
}

environment_state_feature = {
    "dtype": "float32",
    "shape": (4,),
    "names": ["cube_x", "cube_y", "place_x", "place_y"],
}

robot_type = "crane_plus"
repo_id = "crane_plus_parameterized_pick_place"
task_name = "pick_wood_cube_and_place_right"
