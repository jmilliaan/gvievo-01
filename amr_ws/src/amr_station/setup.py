from setuptools import setup

package_name = "amr_station"

setup(
    name=package_name,
    version="0.0.1",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="gvipc",
    maintainer_email="igp.indi.4.0.00@gmail.com",
    description="The MQTT bridge to the station PC (a subset of VDA5050 3.0.0, not compliant).",
    license="Proprietary",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "station_bridge_node = amr_station.station_bridge_node:main",
        ],
    },
)
