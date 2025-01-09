# custom_generator
The goal is to enable generators that can be copied and pickled across versions of python decided on as relevant.

## problem:
There's no robust way to achieve this in cpython (stackless python and maybe others have ways you can achieve this already) as it stands that is also portable across versions.

## solution:
I'm going to emulate what a generator does by writing my own generator type (class) in python and then allow the code to be rewritten in different python versions depending on what version of python the user has. 

The only other possibility I can see potentially working effectively is if you can retrieve the generator internally and then write a C extension out of it. So either you use my solution to make all your function generators that you want to copy a more accessible kind of generator that can be copied/pickled or you write a C extension that accesses (probably) PyThreadState and gets the generator internally then you copy that.

## beyond:

If all goes well, the next goal is to make a copier and pickler for truley copying or pickling a generator by utilizing what I've done at a source code level with adjusting the source code on the fly and apply what's learned to a bytecode level in a way that's also backwards compatible. If it works out, this should allow more generator types to be copyable and pickleable. The learning overhead will be identifying how to maneuver in bytcode robustly and for all versions of python (documentation is not great on byte code in terms of all the different ways it's put together and since the compiler does optimizations it can mess with the predicatability unless you understand the internals; thus it means studying the internals (cpython source code) across all the relevant versions may be necessary).
