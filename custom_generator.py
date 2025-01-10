# -*- coding: utf-8 -*- 
"""
In order to make this module as backwards compatible as possible 
some of the functions used will be written out manually and a 
preprocessor or otherwise condition statemnt will go over what 
changes will be made if any

Backwards compatibility notes of relevance at the moment:

For python 2:

 - classes are not automatically inherited from object
   and therefore you have to do this explicitly
 
 - you need to add a comment specifying an encoding at 
   the the first line of the file

 - range returns a list (use xrange instead)

 - type annotations and the typing module were introduced in python 3.5

 - f-strings were introduced in python 3.6 (use i.e. "%s" % ... instead)
"""

from types import FunctionType
from inspect import getsource,currentframe
import ctypes
from copy import deepcopy,copy
from sys import version_info

## python 2 compatibility ##
if version_info < (3,):
    range = xrange

## this needs to be checked ##
class Send(object):
    """
    Special class specifically used in combination with Generator
    to signal where and what to send
    
    Note: Send should only be used after a yield statement and not
    anywhere else. If used elsewhere or no variable has been sent 
    it will have no effect conceptually.
    """
    def __init__(self,ID):
        if not ID.isalnum():
            raise ValueError("ID must be alpha numeric e.g. ID.isalnum() should return True")
        self.ID=ID

    def __repr__(self):
        return "Send('%s')" % self.ID

def collect_string(line):
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

def get_indent(line):
    """Gets the number of spaces used in an indentation"""
    count=0
    for char in line:
        if char!=" ":
            break
        count+=1
    return count

def skip(iter_val,n):
    """Skips the next n iterations in a for loop"""
    for _ in range(n):
        next(iter_val)

## match case default was introduced in python 3.10
if version_info < (3,10):
    def is_alternative_statement(line):
        return line.startswith("elif") or line.startswith("else")
else:
    def is_alternative_statement(line):
        return line.startswith("elif") or line.startswith("else") or line.startswith("case") or line.startswith("default")
is_alternative_statement.__doc__="Checks if a line is an alternative statement"

"""
TODO:
1. implement exception formmatter                   - format_exception
2. handle loops e.g. for and while                  - _loop_adjust
3. what about yield from                            - _handle_keywords/_cleaned_source_lines
4. make sure inner classes/functions are unaffected - _handle_keywords/_cleaned_source_lines
5. _control_flow_adjust needs fixing e.g. need to 
   dedent the first recognised block to 4 indents
6. fix anything that creates Generator from attrs since attrs will likely change
7. test everything (send probably needs to be re thought as well; make sure lineno is correct)
8. test on async generators
"""
class Generator(object):
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
    # def _handle_keywords(self,source,index,char,number_of_lines):
    #     ## handles keywords ##
    #     temp=self.source[index:]
    #     ## make sure the definitions are unaffected
    #     if temp.startswith("def") or temp.startswith("class"):
    #         reference_indents=get_indent(line)
    #     if temp.startswith("yield"):
    #         skip(source,5)
    #         return "return"
    #     elif temp.startswith("return"):
    #         self.return_linenos+=[number_of_lines+1]

    ## need to adjust for the indentation of the control flow blocks ##
    def _control_flow_adjust(self,lines):
        """
        removes unreachable control flow blocks that 
        will get in the way of the generators state
        """
        current_min=get_indent(lines[self.lineno-1])
        alternative=False
        new_lines=[]
        for line in lines:
            temp=get_indent(line)
            ## skip over all alternative statements until it's not an alternative statement ##
            if alternative and temp > current_min:
                continue
            elif alternative and temp == current_min:
                alternative=is_alternative_statement(line[temp:])
            elif temp < current_min:
                alternative=is_alternative_statement(line[temp:])
                current_min=temp
            if alternative:
                continue
            new_lines+=[line]
        return new_lines

    ## need to add loop adjustments ##
    def _loop_adjust(self,lines):
        """
        adjusts source code about control flow statements
        so that it can be used in a single directional flow
        as the generators states
        """
        ## check for loops ##
        return ""

    def _set_reciever(self,lines):
        """sets the reciever of the generator"""
        self.reciever=None ## used on .send (shouldn't be modified by the user)
        if self.gi_running:
            line=" ".join(lines[0].strip().split()) # .split() followed by .join ensures the spaces are the same
            # as long as it's 'Send(' and Send is Send e.g. locally or globally defined and is correct
            if line[:5]=='Send(' and (self.gi_frame.f_locals.get("Send",None)==Send or globals().get("Send",None)==Send):
                self.reciever=collect_string(line[11:])

    def _create_state(self):
        """
        creates a section of modified source code to be used in a 
        function to act as a generators state

        The approach is as follows:

        Use the entire source code, reducing from the last lineno.
        Adjust the current source code reduction further out of
        control flow statements, loops, etc. then set the adjusted 
        source code as the generators state
        """
        self.lineno+=self.gi_frame.f_lineno-self.init_len
        ## extract the code section ##
        lines=self._source_lines[self.lineno:]
        self._set_reciever(lines)
        self.state="\n".join(self._control_flow_adjust(lines)+self._loop_adjust(lines))

    class frame(object):
        """acts as the initial FrameType"""
        f_locals={}
        f_lineno=0

    init="""
    locals().update(f_locals)
    frame=currentframe()
    frame.f_back.f_locals['self'].gi_frame=frame
    ctypes.pythonapi.PyFrame_LocalsToFast(ctypes.py_object(frame.f_back), ctypes.c_int(0))
"""
    init_len=init.count("\n")+1

    def init_states(self):
        """
        Initializes the state generation

        It goes line by line to find the 
        lines that have the yield statements
        """
        ## define the state related variables in here for ease of use ##
        self.gi_frame=self.frame()
        self.gi_running=False
        self.gi_suspended=False
        self.gi_yieldfrom=None # not sure what this is supposed to return for now
        self.lineno=0 ## the current line number relative to self._source_lines ##
        self.gi_frame.f_lineno=self.init_len
        while self.state and self.lineno not in self.return_linenos:
            try:
                yield self._create_state()
            except StopIteration:
                break

    def _clean_source_lines(self):
        """
        1. fixes any indentation issues (when ';' is used) and skips empty lines
        2. split on "\n" and ";"
        3. join up the line continuations i.e. "\ ... " will be skipped
        """
        ## setup source as an iterator and making sure the first indentation's correct ##
        source=iter(self.source[get_indent(self.source):])
        self.return_linenos=[]
        line,lines,backslash,instring,number_of_lines,reference_indents=" "*4,[],False,False,0,4
        ## enumerate since I want the loop to use an iterator but the 
        ## index is needed to retain it for when it's used on get_indent
        for index,char in enumerate(source):
            ## skip strings ##
            if char=="'" or char=='"' and not backslash:
                instring=(instring + 1) % 2
                line+=char
            elif instring:
                ## keep track of backslash ##
                backslash=(char=="\\")
                line+=char
            ## join everything after the line continuation until the next \n or ; ##
            elif char=="\\":
                skip(source,get_indent(self.source[index+1:])) ## +1 since index: is inclusive ##
            ## create new line ##
            elif char=="\n":
                if line.strip(): ## empty lines are possible ##
                    if get_indent(line) <= reference_indents: ## translate keywords for this generator ##
                        line,reference_indents=self._translate_source_lines(line)
                    lines+=[line]
                    number_of_lines+=1
                line="" ## we can't skip whitespace if we do this ##
            elif char==";":
                if line.strip(): ## empty lines are possible ##
                    if get_indent(line) <= reference_indents:
                        line,reference_indents=self._translate_source_lines(line)
                    lines+=[line]
                    number_of_lines+=1
                line=" "*4
                skip(source,get_indent(self.source[index+1:]))
            else:
                line+=char
        self._source_lines=lines

    def _translate_source(self):
        """
        translates the source code into code 
        that's usable to this custom generator

        It does the following to the source lines:

        1. replace all lines that start with yields with returns to start with
        2. track the linenos of returns
        3. tend to all yield from ... with while loops
        4. tend to all for and while loops if necessary
        """
        ## translate the source code ##
        self.state="\n".join(self._source_lines)

    def __init__(self,FUNC,**attrs):
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
            self.gi_code=compile(FUNC,"","eval")
        else:
            self.source=getsource(FUNC)
            self.gi_code=FUNC.__code__
        ## make sure the source code is standardized and usable by this generator ##
        self._clean_source_lines()
        ## create the states ##
        self.state_generator=self.init_states()

    def __len__(self):
        """
        Gets the number of states for generators with yield 
        statements indented exactly 4 spaces.

        In general, you shouldn't be able to get the length
        of a generator function, but if it's very predictably
        defined then you can.
        """
        def number_of_yields():
            """Gets the number of yields that are indented exactly 4 spaces"""
            for line in self._source_lines:
                indents=get_indent(line)
                if line[indents:].startswith("yield"):
                    if indents > 4:
                        raise TypeError("__len__ is only available where all yield statements are indented exactly 4 spaces")
                    yield 1
        return sum(number_of_yields())

    def __iter__(self):
        """Converts the generator function into an iterable"""
        while True:
            try:
                yield next(self)
            except StopIteration:
                break

    def __next__(self):
        """
        1. change the state
        2. return the value
        """
        # set the next state and setup the function
        next(self.state_generator) ## it will raise a StopIteration for us
        # if not set already
        if not self.gi_running:
            self.gi_running=True
            self.gi_suspended=True
        ## update with the new state and get the frame ##
        exec("def next_state(f_locals):"+self.init+self.state,globals(),locals())
        # get the locals dict, update the line position, and return the result
        try:
            return locals()["next_state"](self.gi_frame.f_locals)
        except Exception as e: ## we should format the exception as it normally would be formmated ideally
            self._format_exception(e)

    def send(self,arg):
        """
        Send takes exactly one arguement 'arg' that 
        is sent to the functions yield variable
        """
        if not self.gi_running:
            raise TypeError("can't send non-None value to a just-started generator")
        if self.reciever:
            self.gi_frame.f_locals()[self.reciever]=arg
        return next(self)

    def close(self):
        """Creates a simple empty generator"""
        self.state_generator=(None for i in ())
        self.gi_frame=None
        self.gi_running=False
        self.gi_suspended=False

    def throw(self,exception):
        """Throws an error at the current line of execution in the function"""
        # get the current position (should be recorded and updated after every execution)
        self._format_exception(exception)

    def _format_exception(self,exception):
        """Raises an exception from the last line in the current state e.g. only from what has been"""
        raise exception

    def _copier(self,FUNC):
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
    ## for copying ##
    def __copy__(self):
        return self._copier(copy)
    def __deepcopy__(self,memo):
        return self._copier(deepcopy)
    ## for pickling ##
    def __getstate__(self):
        """Serializing pickle (what object you want serialized)"""
        _attrs=("source","pos","_states","gi_code","gi_frame","gi_running",
                "gi_suspended","gi_yieldfrom","state_generator","state","reciever")
        return dict(zip(_attrs,(getattr(self,attr) for attr in _attrs)))

    def __setstate__(self,state):
        """Deserializing pickle (returns an instance of the object with state)"""
        Generator(None,**state)

## add the type annotations if the version is 3.5 or higher ##
if (3,5) <= version_info[:3]:
    from typing import Callable,Any,NoReturn,Iterable
    ## Send
    Send.__init__.__annotations__={"ID":str,"return":None}
    Send.__repr__.__annotations__={"return":str}
    ## utility functions
    collect_string.__annotations__={"line":str,"return":str}
    get_indent.__annotations__={"line":str,"return":int}
    skip.__annotations__={"iter_val":Iterable,"n":int,"return":None}
    is_alternative_statement.__annotations__={"line":str,"return":bool}
    ## Generator
    Generator._control_flow_adjust.__annotations__={"lines":list[str],"return":list[str]}
    Generator._set_reciever.__annotations__={"lines":list[str],"return":None}
    Generator._loop_adjust.__annotations__={"lines":list[str],"return":str}
    Generator._create_state.__annotations__={"lineno":int,"return":None}
    Generator.init_states.__annotations__={"return":None}
    Generator._clean_source_lines.__annotations__={"return":None}
    Generator._translate_source.__annotations__={"return":None}
    Generator.__init__.__annotations__={"FUNC":Callable,"return":None}
    Generator.__len__.__annotations__={"return":int}
    Generator.__iter__.__annotations__={"return":iter}
    Generator.__next__.__annotations__={"return":Any}
    Generator.send.__annotations__={"arg":Any,"return":Any}
    Generator.close.__annotations__={"return":None}
    Generator.throw.__annotations__={"exception":Exception,"return":None}
    Generator._format_exception.__annotations__={"exception":Exception,"return":NoReturn}
    Generator._copier.__annotations__={"FUNC":Callable,"return":Generator}
    Generator.__copy__.__annotations__={"return":Generator}
    Generator.__deepcopy__.__annotations__={"memo":dict,"return":Generator}
    Generator.__getstate__.__annotations__={"return":dict}
    Generator.__setstate__.__annotations__={"state":dict,"return":None}
