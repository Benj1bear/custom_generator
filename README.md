# custom_generator
The goal is to enable generators that can be copyied and pickled across versions of python decided on as relevant.

# The problem:
There's no robust way to achieve this in python as it stands that is also portable across versions.

# The solution:
I'm going to emulate what a generator does by writing my own generator type (class) in python and then allow the code to be rewritten in different python versions depending on what version of python the user has. 

The only other possibility I can see potentially working effectively is if you can retrieve the generator internally and then write a C extension out of it. So either you use my solution to make all your function generators that you want to copy a more accessible kind of generator that can be copied/pickled or you write a c extension that accesses (probably) pyThreadstate and gets the generator internally then you copy that.
