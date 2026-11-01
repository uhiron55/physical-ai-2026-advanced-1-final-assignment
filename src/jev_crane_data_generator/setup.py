from glob import glob

from setuptools import find_packages, setup


package_name = "jev_crane_data_generator"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", glob("launch/*.launch.py")),
        ("share/" + package_name + "/worlds", glob("worlds/*.sdf")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="uhiron55",
    maintainer_email="uhiron55@users.noreply.github.com",
    description="Generate CRANE+ demonstrations with Jev action selection.",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "generate_episode = jev_crane_data_generator.generate_episode:main",
            "phase_selector = jev_crane_data_generator.phase_selector:main",
            "act_rollout_controller = jev_crane_data_generator.act_rollout_controller:main",
        ],
    },
)
