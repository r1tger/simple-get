from setuptools import setup

setup(
    name='simpleget',
    version='0.2.2',
    description='Go get it!',
    url='https://github.com/r1tger/simple-get',
    author='Ritger Teunissen',
    author_email='github@ritger.nl',
    packages=['simpleget'],
    install_requires=[
        'click',
        'requests',
        'ngram'
    ],
    entry_points={'console_scripts': [
        'simpleget = simpleget.__main__:main',
    ]},
    zip_safe=False
)
