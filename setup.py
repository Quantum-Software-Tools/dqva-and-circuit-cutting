import setuptools

with open('README.md', 'r') as fh:
    long_description = fh.read()

setuptools.setup(
    name='CutQC',
    version='0.0.1',
    description='Quantum Circuit Cutting',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/weiT1993/circuit_cutting.git',
    packages=setuptools.find_packages(),
    author='weiT1993',
    author_email='tangwei1027@gmail.com',
    license='MIT',
    python_requires='>=3.7',
    zip_safe=False)