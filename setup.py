from setuptools import setup

setup(
    name="clan-bot",
    version="1.0.0",
    install_requires=[
        "python-telegram-bot[job-queue]==20.7",
        "apscheduler==3.10.4"
    ],
)
