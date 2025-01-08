"""
In order to make this module as backwards compatible as possible 
some of the functions used will be written out manually and a 
preprocessor or otherwise condition statemnt will go over what 
changes will be made if any
"""

from typing import Callable,Any
from types import FunctionType
from inspect import getsource
from copy import deepcopy,copy

class Send:
    """
    Special class specifically used in combination with Generator
    to signal where and what to send
    
    Note: Send should only be used after a yield statement and not
    anywhere else. If used elsewhere or no variable has been sent 
    it will have no effect conceptually.
    """
    def __init__(self,ID: str) -> None:
        if not ID.isalnum(): raise ValueError("ID must be alpha numeric e.g. ID.isalnum() should return True")
        self.ID=ID

    def __repr__(self) -> str:
        return f"Send('{self.ID}')"

def collect_string(line: str) -> str:
    """collects a string from a string"""
    if line[0]!="'" or line[0]!='"':
        raise ValueError("'Send' must be given exactly one arguement of type 'str'")
    string=""
    reference_char=line[0]
    line=iter(line)
    for char in line:
        string+=char
        if char=="\\":
            next(line)
            continue
        if char==reference_char:
            break
    return string

def cleaned_source_lines(source: str) -> list[str]:
    """Formats the source code into lines"""
    # skip all strings, replace all ";" with "\n",replace all "\ ... \n" with "", split at \n
    lines=[]
    line=""
    backslash=False
    instring=False
    check_indents=True
    source=iter(source)
    for char in source:
        ## skip strings ##
        if char=="'" or char=='"' and not backslash:
            instring=instring + 1 % 2
            continue
        if instring or (char==" " and not check_indents):
            continue
        ## if not in a string and the indents are fixed, then record the chars ##
        line+=char
        ## keep track of backslash ##
        backslash=(char=="\\")
        ## make sure the line is properly indented ##
        if check_indents:
            count=0
            for char in source:
                if char!=" ":
                    check_indents=False
                    break
                count+=1
            char+=" " * (4 - count % 4) % 4 # % 4 again in case of 0 giving: 4 - 0
        ## create new line ##
        if char=="\n" or char==";":
            lines+=[line]
            line=""
            check_indents=True
    return lines


"""
TODO:
1. implement exception formmatter
2. test everything
"""
class Generator:
    """
    Converts a generator function into a generator 
    function that is copyable (e.g. shallow and deepcopy) 
    and potentially pickle-able
    
    This should be very portable or at least closely so across 
    python implementations ideally.
    
    The dependencies for this to work only requires that you 
    can retrieve your functions source code as a string via
    inspect.getsource.

    How it works:
    
    Basically we emulate the generator process by converting
    it into an on the fly evaluation iterable thus enabling 
    it to be easily copied (Note: deepcopying assumes the
    local variables in the frame can also be copied so if
    you happen to be using a function generator within 
    another function generator then make sure that all
    function generators (past one iteration) are of the 
    Generator type)

    Note: If wanting to use generator expressions i.e.:
    
    (i for i in range(3))
    
    then you can pass it in as a string:
    
    Generator("(i for i in range(3))")
    
    otherwise you could also do something similar to the
    name function in my_pack.name to get the source code
    if desired.
    """
    def _create_state(self,lineno: int) -> None:
        """
        creates a section of modified source code to be used in a 
        function to act as a generators state
        """
        ## get the relevant code section based on the previous end position and the new end position
        self.lineno=self.end_lineno
        ## because they're ints we should be fine with this approach to assignment ##
        self.end_lineno=lineno
        ## extract the code section
        lines=self._source_lines[self.lineno:self.end_lineno]
        self.state="\n".join(lines)
        #####################################################################################################
        if self.state_index: ## assuming it's running
            line=" ".join(lines[0].strip().split()) # .split() followed by .join ensures the spaces are the same
            # as long as it's 'Send(' and Send is Send e.g. locally or globally defined and is correct
            if line[:5]=='Send(' and (self.gi_frame.f_locals.get("Send",None)==Send or globals().get("Send",None)==Send):
                self.reciever=collect_string(line[11:])
            else:
                self.reciever=None
        # update state position
        self.state_index+=1

    def init_states(self) -> None:
        """
        Initializes the state generation
        it goes line by line to find the lines that have the yield statements
        """
        self.state_generator=(self._create_state(lineno) for lineno,line in enumerate(self._source_lines) if line.strip()[:4]=="yield")

    def __len__(self) -> int:
        return sum(1 for line in self._source_lines if line.strip()[:4]=="yield")

    def __init__(self,FUNC: Callable,**attrs) -> None:
        if attrs:
            for attr in ("source","_source_lines","gi_code","gi_frame","gi_running",
                         "gi_suspended","gi_yieldfrom","state","state_index","lineno",
                         "end_lineno","reciever","state_generator"):
                setattr(self,attr,attrs[attr])
            return
        ## you have to pass the source code in manually for generator expressions ##
        ## (getsource does work for lambda expressions but it's got no col_offset which is not useful) ##
        if isinstance(FUNC,str):
            self.source=FUNC
        else:
            self.source=getsource(FUNC)
        ## format into lines
        self._source_lines=cleaned_source_lines(self.source)
        # makes all yields returns, handles .send by setting the variable 
        # used to None, and noting what the reciever is each time
        self.init_states()
        self.gi_code=FUNC.__code__
        self.gi_frame=None
        self.gi_running=False
        self.gi_suspended=False
        self.gi_yieldfrom=None # not sure what this is supposed to return for now
        ## new part which makes it easy to work with ##
        self.state=None
        self.state_index=0 # indicates which state the generator is in
        self.lineno=0
        self.end_lineno=0
        self.reciever=None ## used on .send (shouldn't be modified)

    def __iter__(self) -> iter:
        return (next(self) for i in range(len(self)))
    
    def __next__(self) -> Any:
        """
        1. change the state
        2. return the value
        """
        # if not set already
        if not self.gi_running:
            self.gi_running=True
            self.gi_suspended=True
        # set the next state and setup the function
        next(self.state_generator) ## it will raise a StopIteration for us
        print(repr(self.state))
        code=compile("def next_state(frame: dict):\n\tlocals().update(frame);"+self.state,'','exec')
        FunctionType(code,globals())()
        # get the locals dict, update the line position, and return the result
        try:
            self.gi_frame.f_locals,result=next_state(self.gi_frame.f_locals)
        except Exception as e: ## we should format the exception as it normally would be formmated ideally
            raise e
            #self.format_exception(e)
        return result
    
    def send(self,arg: Any) -> None:
        """
        Send takes exactly one arguement 'arg' that 
        is sent to the functions yield variable
        """
        self.gi_frame.f_locals()[self.reciever]=arg
        return next(self)

    def close(self) -> None:
        """Creates a simple empty generator"""
        self.state_generator=(None for i in ())
        ## remove the frame??

    def throw(self,exception: Exception) -> None:
        """Throws an error at the current line of execution in the function"""
        # get the current position (should be recorded and updated after every execution)
        self.format_exception(exception)
    #####################################################################################################
    ## needs work ----------------------------------------------------------------------- ##
    def format_exception(self,exception: Exception):
        """Raises an exception from the last line in the current state e.g. only from what has been"""
        # not sure how this will work exactly how I want it to ... but I'll think of something
        pass
    #####################################################################################################
    def _copier(self,FUNC: Callable) -> object:
        """copying will create a new generator object but the copier will determine it's depth"""
        attrs=dict(
            zip(
                ((attr,FUNC(getattr(self,attr))) for attr in \
                        ("source","_source_lines","gi_code","gi_frame","gi_running",
                         "gi_suspended","gi_yieldfrom","state","state_index","lineno",
                         "end_lineno","reciever","state_generator"))
                )
            )
        return Generator(None,**attrs)
    # for copying
    def __copy__(self) -> object:
        return self._copier(copy)
    def __deepcopy__(self,memo: dict) -> object:
        return self._copier(deepcopy)
    #####################################################################################################   
    # for pickling
    def __getstate__(self) -> dict:
        """Serializing pickle (what object you want serialized)"""
        _attrs=("source","pos","_states","gi_code","gi_frame","gi_running",
                "gi_suspended","gi_yieldfrom","state_generator","state","reciever")
        return dict(zip(_attrs,(getattr(self,attr) for attr in _attrs)))

    def __setstate__(self,state: dict) -> None:
        """Deserializing pickle (returns an instance of the object with state)"""
        Generator(None,**state)
