# Manual Installation on Linux

The following instructions focus on Debian Linux but should work for Ubuntu as well. 
Note that if you can use Docker, many of these steps are performed for you by Docker when
the container is being created.

## Dependencies

To run the code a few tools are needed:

*  The use of the `bazel` build system is optional but can be helpful.\
   Install from [bazel's homepage](https://docs.bazel.build/versions/master/install.html)

*  We will need Python's `pip` tool to install packages and `git` to manage the source.
  Here is one way to install them:
```
    sudo apt-get install python3-pip
    sudo apt-get install git
```

*  We need Google's `absl` library, as well as `numpy` and `scipy`. Install with
```
   sudo python3 -m pip install absl-py
   sudo python3 -m pip install numpy
   sudo python3 -m pip install scipy
```

* Finally, to get these source onto your computer:
```
    git clone https://github.com/qcc4cp/qcc.git
```

## Build

Much of the code is in Python and will run out of the box.  There is
some C++ for the high performance simulation which requires
configuration. *The Python code will run without C++ acceleration, just much slower.*

There are two ways to build the accelerated library:
1.   Manually, with the script [qcc/make_libxgates.so](../make_libxgates.sh),
     documented [here](README.buildxgates.md).
  

3.   Using `bazel`. This is described in the following. It only works for `bazel`
    version 5, 6, and 7 (not version 8 and `Bzlmod`).
    
The file `src/lib/BUILD` contains the build rule for the C++ xgates
extension module.  This module needs to be able to access the Python
header (`Python.h`), as well as certain `numpy` headers. These files'
location may be different on your build machine. The location
is controlled with the `numpy` and `python` dependencies, which we
explain in a second:

```
cc_library(
    name = "xgates",
    srcs = [
        "xgates.cc",
    ],
    copts = [
        "-O3",
        "-ffast-math",
        "-DNPY_NO_DEPRECATED_API",
        "-DNPY_1_7_API_VERSION",
    ],
    deps = [
        "@third_party_numpy//:numpy",
        "@third_party_python//:python",
    ],
)
```

There is a subtlety about `bazel`: All headers must be within the
source tree, or in `/usr/include/...` To work around this, we have to
point `bazel` to the installation directories of `numpy` and `python`.  

To find the Python headers, you can run
```
python3 -c 'import distutils.sysconfig; print(distutils.sysconfig.get_python_inc())'
```
To find the numpy headers, you can run
```
python3 -c 'import numpy; print(numpy.get_include())'`
```
The specification for the external installations is in the `WORKSPACE`
file. Point `path` to your installation's header files,
excluding the final `include` part of the path. The `include` path is
specified in the files `external/numpy.BUILD` and `external/python.BUILD`. 

*Hint*: For example for `numpy`, assume file `ndarraytype.h` is in a directory 
`.../numpy/core/include/numpy/ndarraytypes.h`. In the specification, 
copy everything up to and not including the `include/...` parts, with a trailing `/`.

*Hint*: For `python` headers, assume `Python.h` is 
in a directory `.../include/python3.9/`. Include
this path in the Python spec below, including the trailing `/`.

```
new_local_repository(
    name = "third_party_numpy",
    build_file = __workspace_dir__ + "/numpy.BUILD",
    # Configure:
    path = "/usr/local/lib/python3.7/dist-packages/numpy/core/",
)

new_local_repository(
    name = "third_party_python",
    build_file = __workspace_dir__ + "/python.BUILD",
    # Configure:
    path = "/usr/include/python3.9",
)
```

Once `xgates` builds successfully, it is imported into `circuit.py`. At the top of this
file is the import statement that might need to be adjusted:

```
# Configure: This line might have to change, depending on
#            the current build environment.
#
# Google internal:
# import xgates
#
# GitHub Linux:
import libxgates as xgates
```

Additionally, to enable Python to find the extension module, make sure
to include in `PYTHONPATH` the directory where the generated
`xgates.so` or `libxgates.so` is being generated. For example:

```
export PYTHONPATH=$PYTHONPATH:/home/usrname/qcc/bazel-bin/src/lib
```

`bazel` also attempts to use the Python 2 interpreter `python`. If it
is not available on a system, install via:

```
sudo apt-get install python
```

## Run
To build the library and test for correct installation, go to `src/lib` and run:

```
    bazel build all
    bazel test ...

    # Make sure to set PYTHONPATH (once):
    export PYTHONPATH=$PYTHONPATH:/home/usrname/qcc/bazel-bin/src/lib

    # Ensure xgates was built properly:
    bazel run circuit_test
```

Refer to the main page to learn how to run the individual algorithms.
Typically, in the `qcc/src` directory, you would run something like:

```
for algo in `ls -1 *py | sed s@.py@@g`
do
   bazel run $algo
done
```

## Minimal Setup
If you can't get `xgates` to build, you can still run all Python algorithms by using the Python interpreter directly, for example:
```
  python3 ./estimate_pi.py
```
All algorithms will work, they might just run much slower.







