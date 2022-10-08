from setuptools import setup

setup(
    name='kinesiscount',
    version='0.0.1',
    description='A Kinesis account balance importer for Beancount',
    url='https://github.com/rosskouk/kinesiscount',
    author='Ross Stewart',
    author_email='rosskouk@gmail.com',
    license='MIT',
    packages=['kinesiscount'],

    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Console',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: MIT License',
        'Natural Language :: English',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 3',
        'Topic :: Office/Business :: Financial :: Accounting'
    ],
)
