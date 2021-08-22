from setuptools import setup, find_packages

PACKAGE_NAME = "pyrla"

setup(
    name=PACKAGE_NAME,
    use_scm_version={
        "fallback_version": "0.1.0",
        },
    packages=find_packages(),
    setup_requires=[
        'setuptools_scm',
        'jinja2',
        ],
    author='Lorenzo Rovigatti',
    author_email='lorenzo.rovigatti@uniroma1.it',
    url='https://github.com/lorenzo-rovigatti/pyrla',
    description='A simple tool to launch multiple processes ',
    long_description=open("./README.md", 'r').read(),
    long_description_content_type="text/markdown",
    license='GNU GPL 3.0',
    zip_safe=False,
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Console",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        ],
    entry_points = {
        'console_scripts': ['pyrla=pyrla:main'],
    },
    include_package_data=True,
)
