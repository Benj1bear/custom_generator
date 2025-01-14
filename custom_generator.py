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

## Note: line.startswith("except") will need to put a try statement in front (if it's not there e.g. is less than the minimum indent) ##
## match case default was introduced in python 3.10
if version_info < (3,10):
    def is_alternative_statement(line):
        return line.startswith("elif") or line.startswith("else")
else:
    def is_alternative_statement(line):
        return line.startswith("elif") or line.startswith("else") or line.startswith("case") or line.startswith("default")
is_alternative_statement.__doc__="Checks if a line is an alternative statement"

def extract_iter(line):
    """
    Extracts the iterator from a for loop
    
    e.g. we extract the second ... in:
    for ... in ...:
    """
    # 1. get the length of the ids on the left hand side of the "in" keyword
    ID=""
    for index,char in enumerate(line):
        if char.isalphnum():
            ID+=char
            if ID=="in":
                break
        else:
            ID=""
    # 2. collect everything on the right hand side of the "in" keyword
    # 3. remove the end colon
    ## +1 for 0 based indexing, +1 for whitespace after ##
    return line[index+2:][:-1]

def control_flow_adjust(lines):
    """
    removes unreachable control flow blocks that 
    will get in the way of the generators state

    Note: it assumes that the line is cleaned,
    in particular, that it starts with an 
    indentation of 4

    It will also add 'try:' when there's an
    'except' line on the next minimum indent
    """
    init_min=get_indent(lines[0])
    if init_min == 4:
        return lines
    alternative,new_lines=False,[]
    current_min=init_min
    for line in lines: ## is having no lines possible? This would raise an error ##
        temp=get_indent(line)
        ## skip over all alternative statements until it's not an alternative statement ##
        if alternative and temp > current_min:
            continue
        elif temp == current_min:
            alternative=is_alternative_statement(line[temp:])
        elif temp < current_min:
            current_min=temp
            ## check for changes ##
            temp_line=line[temp:]
            if temp_line.startswith("except"):
                new_lines=[" "*temp+"try:"]+new_lines+[line]
                continue
            alternative=is_alternative_statement(temp_line)
        if alternative:
            continue
        ## add the line (adjust if indentation is not 4) ##
        if current_min != 4:
            new_lines+=[line[init_min-4:]] ## -4 adjusts the initial block to an indentation of 4 ##
        else:
            new_lines+=[line]
    return new_lines

def temporary_loop_adjust(line):
    """
    Formats the current code block 
    being executed such that all the
    continue -> break;
    break -> empty the current iter; break;
    """
    indent=get_indent(line)
    temp=line[indent:]
    indent=" "*(indent+4) ## +4 since it's in a newly created block ##
    if temp.startswith("continue"):
        return indent+"break"
    elif temp.startswith("break"):
        return [indent+"locals()['.continue']=False",indent+"break"]
    return " "*4+line

def send_adjust(line):
    flag=0
    parts=line.split("=")
    for index,node in enumerate(parts):
        node=node[get_indent(node):]
        if node.startswith("yield from "):
            flag=1
            break
        if node.startswith("yield "):
            flag=2
            break
        if not node.isalnum(): ## makes sure we're assigning to a variable ##
            break
    if flag:
        return flag,["=".join(parts[index:]),"=".join(parts[:index])+"=locals()['.send']"]
    return None,None

class frame(object):
    """acts as the initial FrameType"""
    f_locals={".send":None}
    f_lineno=0

"""
TODO:
1. think about getsource in relation to generator expressions that sometimes   - __init__
   don't get their source retrieved and if there's also a col_offset
2. fix for running generators                                                  - __init__
3. check whitespace, linenos, attrs, e.g. the smaller details to clean up      - _clean_source_lines and others involved in _create_state
4. format errors                                                               - throw
5. write tests
6. make an asynchronous verion? async generators have different attrs i.e. gi_frame is ag_frame
 - maybe make a preprocessor to rewrite some of the functions in Generator for ease of development
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
    
    You can use inspect.getsource to get the source code
    on either its gi_code or gi_frame but you need to know
    it's current col position as well.
    """

    def _custom_adjustment(self,line,lineno):
        """
        It does the following to the source lines:

        1. replace all lines that start with yields with returns to start with
        2. make sure the generator is closed on regular returns
        3. save the iterator from the for loops replacing with a nonlocal variation
        4. tend to all yield from ... with the same for loop variation
        """
        number_of_indents=get_indent(line)
        if self._skip_indent <= number_of_indents: ## skips if greater to avoid definitions ##
            indent=" "*number_of_indents
            temp_line=line[number_of_indents:]
            if temp_line.startswith("def ") or temp_line.startswith("async def ") or temp_line.startswith("class ") or temp_line.startswith("async class "):
                self._skip_indent=number_of_indents
            else:
                self._skip_indent=0
                if temp_line.startswith("yield from "):
                    return [indent+"currentframe().f_back.f_locals['.yieldfrom']="+temp_line[11:],
                            indent+"for currentframe().f_back.f_locals['.i'] in currentframe().f_back.f_locals['.yieldfrom']:",
                            indent+"    return currentframe().f_back.f_locals['.i']"]
                elif temp_line.startswith("yield "):
                    return [indent+"return"+temp_line[5:]] ## 5 to retain the whitespace ##
                elif temp_line.startswith("for "):
                    self.jump_positions+=[(lineno,None)]
                    self._jump_stack+=[(number_of_indents,len(self.jump_positions)-1)]
                    return [indent+"currentframe().f_back.f_locals['.iter']=iter(%s)" % extract_iter(temp_line[4:]),
                            indent+"for i in currentframe().f_back.f_locals['.iter']:"]
                elif temp_line.startswith("while "):
                    self.jump_positions+=[(lineno,None)]
                    self._jump_stack+=[(number_of_indents,len(self.jump_positions)-1)]
                elif temp_line.startswith("return "):
                    ## close the generator then return ##
                    [indent+"currentframe().f_back.f_locals['self'].close()",line]
                ## handles the .send method ##
                flag,adjustment=send_adjust(line)
                if flag:
                    if flag==1:
                        return [indent+"return"+adjustment[0][5:]]+adjustment[1]
                    else:
                        return [indent+"currentframe().f_back.f_locals['.yieldfrom']="+adjustment[0][11:],
                                indent+"for currentframe().f_back.f_locals['.i'] in currentframe().f_back.f_locals['.yieldfrom']:",
                                indent+"    return currentframe().f_back.f_locals['.i']"]+adjustment[1]
        return [line]

    def _clean_source_lines(self):
        """
        source: str

        returns source_lines: list[str],return_linenos: list[int]

        1. fixes any indentation issues (when ';' is used) and skips empty lines
        2. split on "\n", ";", and ":"
        3. join up the line continuations i.e. "\ ... " will be skipped
        
        additionally, custom_adjustment will be called on each line formation as well
        """
        ## for loop adjustments ##
        self.jump_positions,self._jump_stack,self._skip_indent=[],[],0
        ## setup source as an iterator and making sure the first indentation's correct ##
        source=enumerate(self.source[get_indent(source):])
        line,lines,backslash,instring,indented,space=" "*4,[],False,False,False,0
        ## enumerate since I want the loop to use an iterator but the 
        ## index is needed to retain it for when it's used on get_indent
        for index,char in source:
            ## skip strings ##
            if char=="'" or char=='"' and not backslash:
                instring=(instring + 1) % 2
                line+=char
            elif instring:
                ## keep track of backslash ##
                backslash=(char=="\\")
                line+=char
            ## makes the line singly spaced while retaining the indentation ##
            elif char==" ":
                if indented:
                    if space+1!=index:
                        line+=char
                else:
                    line+=char
                    if space+1!=index:
                        indented=True
                space=index
            ## join everything after the line continuation until the next \n or ; ##
            elif char=="\\":
                skip(source,get_indent(source[index+1:])) ## +1 since index: is inclusive ##
            ## create new line ##
            elif char in "\n;:":
                if char==":":
                    line+=char
                if not line.isspace(): ## empty lines are possible ##
                    reference_indent=get_indent(line)
                    while reference_indent == self._jump_stack[-1][0]:
                        pos=self._jump_stack.pop()
                        reference_indent=pos[0]
                        self.jump_positions[pos[1]][1]=len(lines)+1
                    lines+=self._custom_adjustment(line)
                if char in ":;":
                    line=" "*4
                    skip(source,get_indent(source[index+1:]))
                else:
                    line=""
            else:
                line+=char
        if self._jump_stack:
            ## in case you get a for loop at the end ##
            for reference_indent in range(get_indent(line),0,-4):
                if reference_indent == self._jump_stack[-1][0]:
                    self.jump_positions[self._jump_stack.pop()[1]][1]=len(lines)+1
        ## are not used by this generator (was only for formatting source code) ##
        del self._jump_stack,self._skip_indent
        return lines

    def _loop_adjust(self,lines):
        """
        adjusts source code about control flow statements
        so that it can be used in a single directional flow
        as the generators states

        to handle nesting of loops it will simply join
        all the loops together and run them where the 
        outermost nesting will be the final section that
        also contains the rest of the source lines as well
        """
        positions=iter(self.jump_positions)
        for pos in positions: ## importantly we go from start to finish to capture nesting loops ##
            if self.lineno < pos[0]:
                break
            elif self.lineno < pos[1]:
                ## handle nested loops ##
                end_pos=pos[1]
                ## is the outermost loop ##
                loops=[self._source_lines[pos[0]:]]
                for pos in positions:
                    if self.lineno >= pos[1]:
                        break
                    loops+=[self._source_lines[pos[0]:pos[1]]]
                    # new_state="\n".join(temp)+"\n"+new_state
                ## make sure the break statement adjustment can work ##
                loops[-1]=["if locals()['.continue']:"]+[" "*4+line for line in loops[-1]]
                loops="\n".join("\n".join(loop) for loop in loops)
                ## adjust the current code block then return the combined result ##
                current_code=[]
                for line in control_flow_adjust(lines[:end_pos]):
                    ## we do it this way since you can get [...,...] which won't work as a list comprehension ##
                    current_code+=temporary_loop_adjust(line)
                current_code=["while True:"]+current_code+[" "*4+"break"]
                return "\n".join(current_code+loops)
        return "\n".join(control_flow_adjust(lines))

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
        ## used on .send (shouldn't be modified by the user)
        self.reciever=self._set_reciever(lines)
        self.state=self._loop_adjust(lines)

    ## try not to use variables here (otherwise it can mess with the state) ##
    init="""
    locals().update(currentframe().f_back.f_locals['self'].gi_frame.f_locals)
    currentframe().f_back.f_locals['self'].gi_frame=currentframe()
    ctypes.pythonapi.PyFrame_LocalsToFast(ctypes.py_object(currentframe().f_back), ctypes.c_int(0))
"""
    init_len=init.count("\n")+1

    def init_states(self):
        """
        Initializes the state generation

        It goes line by line to find the 
        lines that have the yield statements
        """
        while self.state:
            try:
                yield self._create_state()
            except StopIteration:
                break

    def __init__(self,FUNC,overwrite=False):
        """
        Takes in a function or its source code as the first arguement

        Otherwise it takes a dictionary of attributes as the keyword arguements

        Note:
         - gi_running: is the generator currently being executed
         - gi_suspended: is the generator currently paused e.g. state is saved

        """
        if isinstance(FUNC,dict):
            for attr in ("source","gi_code","gi_frame","gi_running","gi_suspended","gi_yieldfrom",
                         "_source_lines","lineno","state"):
                setattr(self,attr,FUNC[attr])
        elif hasattr(FUNC,"gi_code"): ## an initialized generator ##
            self.source=getsource(FUNC.gi_code)
            # i.e. get the running line + col_offset (since the source code is can likely be not well formatted)
            self.source=self.source.split("\n")[FUNC.gi_frame.f_lineno-FUNC.gi_code.co_firstlineno:]
            self.source[0]=self.source[0][col_offset:]
            self.source="\n".join(self.source)
            self._source_lines=self._clean_source_lines()
            self.gi_code=FUNC.gi_code
            self.gi_frame=FUNC.gi_frame
            ## gi_yieldfrom was introduced in python version 3.5 ##
            if hasattr(FUNC,"gi_yieldfrom"):
                self.gi_yieldfrom=FUNC.gi_yieldfrom
            else:
                self.gi_yieldfrom=None
            self.gi_suspended=True
        else:
            ## getsource does work for expressions but it's got no col_offset which is not useful ##
            ## but it may still work with some adjustments (maybe) ##
            if isinstance(FUNC,str): ## from source code ##
                self.source=FUNC
                self.gi_code=compile(FUNC,"","eval")
            elif isinstance(FUNC,FunctionType): ## a generator function ##
                self.source=getsource(FUNC)
                self.gi_code=FUNC.__code__
            ## make sure the source code is standardized and usable by this generator ##
            self._source_lines=self._clean_source_lines()
            ## create the states ##
            self.gi_frame=frame()
            self.gi_suspended=False
            ## indicates what iterable is being yield from ##
            ## when the yield is a yield from (introduced in python version 3.3) ##
            self.gi_yieldfrom=None
            ############################################################
            self.lineno=0 ## the current line number relative to self._source_lines ##
            self.gi_frame.f_lineno=self.init_len # is this necessary??
            ############################################################
        self.gi_running=False
        self.state_generator=self.init_states()
        if overwrite:
            if hasattr(FUNC,"__code__"):
                currentframe().f_back.f_locals[FUNC.__code__.co_name]=self
            else:
                currentframe().f_back.f_locals[FUNC.gi_code.co_name]=self

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
                temp=line[indents:]
                if temp.startswith("yield") and not temp.startswith("yield from"):
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
        ## update with the new state and get the frame ##
        exec("def next_state():"+self.init+self.state,globals(),locals())
        try: # get the locals dict, update the line position, and return the result
            self.gi_running=True
            result=locals()["next_state"]()
            self.gi_running=False
            return result
        except Exception as e: ## we should format the exception as it normally would be formmated ideally
            self.throw(e)

    def send(self,arg):
        """
        Send takes exactly one arguement 'arg' that 
        is sent to the functions yield variable
        """
        if self.gi_yieldfrom:
            return self.gi_yieldfrom.send(arg)
        if not self.gi_running:
            raise TypeError("can't send non-None value to a just-started generator")
        if self.reciever:
            self.gi_frame.f_locals()[".send"]=arg
        return next(self)

    def close(self):
        """Creates a simple empty generator"""
        self.state_generator=iter(())
        self.gi_frame=None
        self.gi_running=False
        self.gi_suspended=False

    def throw(self,exception):
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
        return Generator(attrs)
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
        Generator(state)

## add the type annotations if the version is 3.5 or higher ##
if (3,5) <= version_info[:3]:
    from typing import Callable,Any,NoReturn,Iterable
    import types
    ## utility functions
    get_indent.__annotations__={"line":str,"return":int}
    skip.__annotations__={"iter_val":Iterable,"n":int,"return":None}
    is_alternative_statement.__annotations__={"line":str,"return":bool}
    extract_iter.__annotations__={"line":str,"return":str}
    control_flow_adjust.__annotations__={"lines":list[str],"return":list[str]}
    temporary_loop_adjust.__annotations__={"line":str,"return":list[str]}
    send_adjust.__annotations__={"line":str,"return":tuple[None|int,None|list[str,str]]}
    ## Generator
    Generator._custom_adjustment.__annotations__={"line":str,"lineno":int,"return":list[str]}
    Generator._clean_source_lines.__annotations__={"source":str,"return":list[str]}
    Generator._set_reciever.__annotations__={"lines":list[str],"return":str}
    Generator._loop_adjust.__annotations__={"lines":list[str],"return":str}
    Generator._create_state.__annotations__={"return":None}
    Generator.init_states.__annotations__={"return":Iterable}
    Generator.__init__.__annotations__={"FUNC":Callable|str|types.Generator|dict,"return":None}
    Generator.__len__.__annotations__={"return":int}
    Generator.__iter__.__annotations__={"return":Iterable}
    Generator.__next__.__annotations__={"return":Any}
    Generator.send.__annotations__={"arg":Any,"return":Any}
    Generator.close.__annotations__={"return":None}
    Generator.throw.__annotations__={"exception":Exception,"return":NoReturn}
    Generator._copier.__annotations__={"FUNC":Callable,"return":Generator}
    Generator.__copy__.__annotations__={"return":Generator}
    Generator.__deepcopy__.__annotations__={"memo":dict,"return":Generator}
    Generator.__getstate__.__annotations__={"return":dict}
    Generator.__setstate__.__annotations__={"state":dict,"return":None}
