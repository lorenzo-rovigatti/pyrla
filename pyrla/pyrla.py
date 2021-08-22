#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#   Copyright (C) 2011 Lorenzo Rovigatti
#
#   pyrla is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation; either version 2 of the License, or
#   (at your option) any later version.
#
#   pyrla is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with pyrla; if not, write to the Free Software
#   Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

#-------------------------------------------------------------------------------- 
# TODO: 
#    - add PreJobsLaunch and PostJobsLaunch (executed at a 'global' level 
#        before and after the spawning of the threads)
#-------------------------------------------------------------------------------- 

import sys
import re
import threading
import queue
import os
import subprocess
import shutil
import collections
from time import sleep
# used to process mathematical expressions
from math import * #@UnusedWildImport

try:
    import jinja2
    JINJA_AVAILABLE = True
except ModuleNotFoundError:
    JINJA_AVAILABLE = False

MAX_STATES = 100000

# static class
class Logger():
    debug_level = 0
    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3
    CRITICAL = 4

    messages = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

    @staticmethod
    def log(msg, level):
        if level < Logger.debug_level: 
            return

        print("%s: %s" % (Logger.messages[level], msg))
        
        
class KeyModifier(object):
    def __init__(self, modified_key, conditions):
        self.modified_key = modified_key
        self.printed_condition_warnings = []
        
        self._parse_conditions(conditions)
        
    def _parse_conditions(self, conditions):
        self.conditions = {}
        for cond in conditions.split(","):
            key, value = [x.strip() for x in cond.partition("=")[0:3:2]]
            if key == self.modified_key.key:
                Logger.log("A modifier for the key '%s' contains a condition based on itself" % key, Logger.WARNING)
            self.conditions[key] = value
            
    def applies_to(self, key_value_dict):
        for cond_key, cond_value in self.conditions.items():
            if cond_key in key_value_dict:
                if cond_value != key_value_dict[cond_key]():
                    return False
            else:
                # we do this to avoid printing the same warning more than once
                if cond_key not in self.printed_condition_warnings:
                    Logger.log("A modifier for the key '%s' contains the undefined condition key '%s'" % (self.modified_key.key, cond_key), Logger.WARNING)
                    self.printed_condition_warnings.append(cond_key)
                    return False
            
        return True
    
    def value(self):
        self.modified_key.expand()
        return self.modified_key()
        
        
class BaseKey(object):
    SPECIAL_KEYS = ("CopyTo", "CopyFrom", "CopyToWrite", "Execute", "DirectoryStructure",
                    "ContemporaryJobs", "Subdirectories", "CopyObjects", "WaitingTime",
                    "Times", "InputSeparator", "Exclusive", "LastFile", "Relaunch", "InputType",
                    "PreExecute", "PostExecute")

    def __init__(self, key, value, key_value_dict):
        self.key = key
        self.raw_value = value
        if len(value) > 0 and self.raw_value[0] == '"' and self.raw_value[-1] == '"':
            self.raw_value = self.raw_value[1:-1]
        self.value = self.raw_value
        # special keys (aka keywords like Input, DirectoryStructure, ecc) need to be handled in a different way
        self.special = (self.key in BaseKey.SPECIAL_KEYS)
        
        self.key_value_dict = key_value_dict
        # TODO: make it a set
        self.depends_on_keys = []
        self.modifiers = []

        self.compute_dependencies()

    def __cmp__(self, other):
        if other.depends_on(self.key):
            return - 1
        elif self.depends_on(other.key):
            return 1
        else:
            ih = self.has_dependencies()
            oh = other.has_dependencies()
            if ih and not oh:
                return 1
            elif oh and not ih:
                return -1

            return 0

    # returns False if there is no next value
    def set_next_value(self):
        return False

    # this is a recursive function: if A depends on B and B depends on C
    # then A.depends_on(C) will return True
    def depends_on(self, key):
        if key in self.depends_on_keys:
            return True
        for k in self.depends_on_keys:
            if k not in self.key_value_dict:
                Logger.log("Key '%s' (which is expanded by '%s') is not defined" % (k, self.key), Logger.CRITICAL)
                exit(1)
                
            if self.key_value_dict[k].depends_on(self.key):
                Logger.log("Circular dependency between '%s' and '%s', aborting" % (self.key, k), Logger.CRITICAL)
                exit(1)
                
            if self.key_value_dict[k].depends_on(key):
                return True

        return False

    def has_dependencies(self):
        return (len(self.depends_on_keys) > 0)
    
    def has_modifiers(self):
        return (len(self.modifiers) > 0)

    def compute_dependencies(self):
        found_keys = re.findall('\$\([\w\[\]]+\)' , self.raw_value)

        for fk in found_keys:
            # we get rid of $( and )
            key = fk[2:-1]
            self.depends_on_keys.append(key)

    def is_iterable(self):
        return (type(self.value) == list)

    def __call__(self):
        return self.value

    def __repr__(self):
        return "%s: %s = %s" % (self.__class__.__name__, self.key, self())
    
    def add_modifier(self, modified_key, conditions):
        new_modifier = KeyModifier(modified_key, conditions)
        self.modifiers.append(new_modifier)
        self.depends_on_keys += list(new_modifier.conditions.keys())
        
    def _expand_modifiers(self):
        modifiers_applied = 0
        for m in self.modifiers:
            if m.applies_to(self.key_value_dict):
                self.value = m.value()
                modifiers_applied += 1
                
        if modifiers_applied > 1:
            Logger.log("Multiple modifiers for key '%s' applied" % (self.key), Logger.WARNING)
                
        return modifiers_applied > 0
    
    def expand_base_value(self):
        self.value = self.raw_value

    def expand(self):
        if not self._expand_modifiers():
            self.expand_base_value()


class MultipleKey(BaseKey):
    def __init__(self, key, value, key_value_dict):
        BaseKey.__init__(self, key, value, key_value_dict)
        self.value = []
        self.counter = 0

    def __call__(self):
        return self.value[self.counter]

    def reset(self):
        self.counter = 0

    def set_next_value(self):
        self.counter += 1
        if self.counter < len(self.value):
            return True
        else:
            self.reset()
            return False

    def expand_base_value(self):
        if self.special == False:
            self.value = self.raw_value.split()
        else:
            self.value = [self.raw_value, ]
        
        
class FileKey(MultipleKey):
    RE = "^LF"
    
    def __init__(self, key, value, key_value_dict):
        filename = value[2:].strip()
        try:
            inp = open(filename, "r")
            loaded_value = " ".join(inp.readlines())
            inp.close()
        except IOError:
            Logger.log("File '%s' not found" % filename, Logger.CRITICAL)
            exit(1)
        
        MultipleKey.__init__(self, key, loaded_value, key_value_dict)


class ExpressionKey(BaseKey):
    def __init__(self, key, value, key_value_dict):
        BaseKey.__init__(self, key, value, key_value_dict)

    def expand_variables(self):
        # expand the variables found by compute_dependencies
        for key in self.depends_on_keys:
            try:
                dep_value = self.key_value_dict[key]()
                self.value = self.value.replace("$(%s)" % key, dep_value)
            except Exception as e:
                Logger.log("Can't expand variable '%s' in line '%s' (error: %s)" % (key, self.raw_value, e), Logger.WARNING)

    def expand_math(self):
        # expand mathematical expressions
        math_expressions = re.findall('\$\{.*?\}' , self.value)

        for mk in math_expressions:
            try:
                # we have to get rid of ${ and }
                res = eval(mk[2:-1])
                self.value = self.value.replace(mk, str(res))
            except Exception as e:
                Logger.log("Can't expand mathematical expression '%s' in line '%s' (error: %s)" % (mk, self.raw_value, e), Logger.WARNING)

    def expand_base_value(self):
        self.value = self.raw_value
        self.expand_variables()
        self.expand_math()
        

class BashKey(ExpressionKey):
    RE = '^\$b\{.*?\}$'
    
    def __init__(self, key, value, key_value_dict):
        ExpressionKey.__init__(self, key, value, key_value_dict)
        
    def expand_base_value(self):
        ExpressionKey.expand_base_value(self)
        found_keys = re.findall(BashKey.RE , self.value)
        if len(found_keys) != 1:
            Logger.log("Can't expand key '%s' in line '%s' (error: bash commands should be enclosed between '$b{' and '}')" % (self.key, self.raw_value), Logger.WARNING)
        else:
            command = found_keys[0][3:-1]
            # the universal_newlines=True makes Popen use str instead of bytes (among other side effects)
            p = subprocess.Popen(command, stdout=subprocess.PIPE, shell=True, universal_newlines=True)
            out = p.communicate()[0]
            self.value = out.strip()
            
            if p.returncode != 0:
                Logger.log("The bash command '%s' associated to the key '%s' returned %d (!= 0)" % (command, self.key, p.returncode), Logger.WARNING)


class ExpressionMultipleKey(MultipleKey, ExpressionKey):
    RE = "^F([\s]+.*?[\s]+)T([\s]+.*?[\s]+)V([\s]+.*?[\s]*)$"

    def __init__(self, key, value, key_value_dict):
        MultipleKey.__init__(self, key, value, key_value_dict)
        ExpressionKey.__init__(self, key, value, key_value_dict)

    def expand_complex_math(self):
        compl_found = re.findall(ExpressionMultipleKey.RE, self.value)[0]

        if len(compl_found) != 3:
            Logger.log("Can't expand complex mathematical expression in line '%s' (error: malformed line)" % (self.raw_value), Logger.CRITICAL)
            exit(1)

        self.value = []
        next_v = float(compl_found[0])
        target = float(compl_found[1])
        old_dist = fabs(next_v - target)
        if next_v <= target:
            condition = lambda test, tar: test < tar
        else:
            condition = lambda test, tar: test > tar

        end = False
        while not end:
            # this is a (dirty) way to understand if next_v is (or the user wants it to be) an integer or not
            if fabs(next_v - round(next_v)) < 1e-6:
                next_v = int(round(next_v))
            self.value.append(str(next_v))
            if len(self.value) > MAX_STATES:
                Logger.log("Too many values generated by the complex math expression '%s'" % self.raw_value, Logger.CRITICAL)
                exit(1)
            try:
                next_v = eval(str(next_v) + compl_found[2])
            except Exception as e:
                Logger.log("Can't expand complex math expression in line '%s' (error: %s)" % (self.raw_value, e), Logger.CRITICAL)
                exit(1)

            new_dist = fabs(next_v - target)
            if not condition(next_v, target):
                end = True
            elif new_dist > old_dist:
                Logger.log("The 'Via' parameter in the complex math expression '%s' is pointing in the wrong direction" % self.raw_value, Logger.CRITICAL)
                exit(1)
            old_dist = new_dist


    def expand_base_value(self):
        ExpressionKey.expand_base_value(self)
        self.expand_complex_math()
        
        
class KeyFactory(object):
    def _is_base(key, value):
        # if the value contains one or more bash-like commands
        protected_keywords = ["cp", "mv", "if", "then", "fi", "for", "done"]
        # split the string using spaces and semi-colons as delimiters 
        tokens = re.split(" |;", value);
        for token in tokens:
            if token in protected_keywords:
                Logger.log("The '%s' key looks like a list of values but contains the token '%s': I will assume it is part of a bash-like command and hence treat it like a single key " % (key, token), Logger.WARNING)
                return True
            
        # if the value is empty, surrounded by quotes or it's just a single word
        if len(value) == 0 or (value[0] == '"' and value[-1] == '"') or len(value.split()) == 1:
            return True
            
        return False
    _is_base = staticmethod(_is_base)
    
    def get_key(key, value, key_value_dict):
        if re.search(ExpressionMultipleKey.RE, value) != None:
            return ExpressionMultipleKey(key, value, key_value_dict)
        elif re.search(FileKey.RE, value) != None:
            return FileKey(key, value, key_value_dict)
        elif re.search(BashKey.RE, value) != None:
            return BashKey(key, value, key_value_dict)
        elif "$(" in value or "${" in value:
            return ExpressionKey(key, value, key_value_dict)
        elif KeyFactory._is_base(key, value):
            return BaseKey(key, value, key_value_dict)
        else:
            return MultipleKey(key, value, key_value_dict)
    get_key = staticmethod(get_key)


class KeyValueDict(collections.UserDict):
    REQUIRED_BASEKEYS = ("CopyFrom", "ContemporaryJobs")
    PROTECTED_KEYS = ("JOB_ID", "BASE_DIR")
    ACCEPTED_INPUT_TYPES = ("OptionList", "LAMMPS", "Jinja2")

    def __init__(self, input_file):
        collections.UserDict.__init__(self)
        
        self.input = input_file
        
        self["JOB_ID"] = KeyFactory.get_key("JOB_ID", "-1", self)
        self["BASE_DIR"] = KeyFactory.get_key("BASE_DIR", os.getcwd(), self)
        
        self.modifiers = []
        
        if not os.path.isfile(input_file):
            Logger.log("Input file '%s' not found" % input_file, Logger.CRITICAL)
            exit(1)

    def check(self):
        if not "Execute" in self:
            Logger.log("Mandatory key 'Execute' missing", Logger.CRITICAL)
            exit(1)
            
        if "InputType" in self:
            if self["InputType"]() not in KeyValueDict.ACCEPTED_INPUT_TYPES:
                Logger.log("Invalid InputType. The supported values are %s" % ", ".join(KeyValueDict.ACCEPTED_INPUT_TYPES), Logger.CRITICAL)
                exit(1)
        else:
            self["InputType"] = KeyFactory.get_key("InputType", "OptionList", self)
            
        if self["InputType"] == "Jinja2" and not JINJA_AVAILABLE:
            Logger.log("The jinja2 python package required by InputType = \"Jinja2\" was not found, aborting", Logger.CRITICAL)
            exit(1)

        if not "Exclusive" in self:
            self["Exclusive"] = KeyFactory.get_key("Exclusive", "False", self)
        else:
            self["Exclusive"].raw_value = self["Exclusive"].raw_value.capitalize()
            
        if not "PreExecute" in self:
            self["PreExecute"] = KeyFactory.get_key("PreExecute", "", self)
        if not "PostExecute" in self:
            self["PostExecute"] = KeyFactory.get_key("PostExecute", "", self)

        for bk in KeyValueDict.REQUIRED_BASEKEYS:
            if bk in self:
                if self[bk].__class__.__name__ != BaseKey.__name__:
                    Logger.log("The key '%s' may not be a list nor contain expressions" % bk, Logger.CRITICAL)
                    exit(1)
                    
        # check that there are no modifiers associated to undefined keys 
        for mod in self.modifiers:
            if mod.key not in self:
                Logger.log("There is a modifier associated to the undefined key '%s'" % mod.key, Logger.WARNING)

    def parse(self):
        with open(self.input) as f:
            for line in f.readlines():
                self.fill_lists(line)

        self.check()

    def fill_lists(self, line):
        # remove anything that comes after a hash sign
        s_line = line.strip().split("#", 1)[0].strip()
        
        if len(s_line) > 0:
            my_list = s_line.partition('=')
            if my_list[1] == '':
                Logger.log("Malformed line '%s'" % s_line, Logger.WARNING)
                return

            key = my_list[0].strip()
            if key in KeyValueDict.PROTECTED_KEYS:
                Logger.log("'%s' is a protected keyword and cannot be used as a key" % key, Logger.CRITICAL)
                exit(1)
                
            value = my_list[2].strip()
            # check whether the line specifies a modifier (i.e. a value that should be used only if some conditions are met)
            if "@@" in my_list[2]:
                rhs, conditions = [x.strip() for x in my_list[2].partition("@@")[0:3:2]]
                modified_value = KeyFactory.get_key(key, rhs, self)
                if key not in self:
                    Logger.log("The modifier '%s' appears before the key it is supposed to act on. This is not supported" % key, Logger.CRITICAL)
                    exit(1)
                    
                # apply the modifier
                self[key].add_modifier(modified_value, conditions)
            else:
                if key in self:
                    Logger.log("Key '%s' is defined more than once, I'll keep the first definition found, thereby throwing away '%s'"
                               % (key, my_list[2].strip()), Logger.WARNING)
                    return

                self[key] = KeyFactory.get_key(key, value, self)


# our worker!
class Job(threading.Thread):

    class SafeError(Exception):
        def __init__(self, value):
            self.value = value
        def __str__(self):
            return self.value

    queue = queue.Queue(1)
    dir_lock = threading.Lock()
    dir_taken = {}
    dir_taken_lock = threading.Lock()
    # contains the lines taken from the original copy_from file
    copy_from_lines = None

    def __init__(self, tid, safe):
        threading.Thread.__init__(self)
        self.tid = tid
        self.original_dir = os.getcwd()
        self.working_dir = os.getcwd()
        self.safe = safe

    def create_copy_to(self):
        if "CopyFrom" not in self.state:
            return

        sep = self.state["InputSeparator"] if "InputSeparator" in self.state else "="

        if "CopyTo" in self.state:
            name = self.state['CopyTo']
        else:
            if os.path.samefile(self.working_dir, self.original_dir):
                raise Job.SafeError("Job %d: I refuse to overwrite the CopyFrom file '%s', you should either use CopyTo to write to a different filename or DirectoryStructure to set a different target directory" % (self.tid, self.state['CopyFrom']))
            else:
                name = self.state['CopyFrom']

        # with list(set(*)) we are sure that copy_list contains only unique elements
        if "CopyToWrite" in self.state:
            copy_list = list(set(self.state['CopyToWrite'].split()))
        else:
            copy_list = []

        copy_not_found = []
        for k in copy_list:
            if k not in self.state:
                copy_list.remove(k)
                copy_not_found.append(k)

        if len(copy_not_found) != 0:
            Logger.log("Job %d: keys '%s' are in CopyToWrite but are not defined" % (self.tid, " ".join(copy_not_found)), Logger.WARNING)

        out = os.path.join(self.working_dir, name)
        if self.safe and os.path.exists(out):
            raise Job.SafeError("Job %d: can't overwrite file '%s' in safe mode, aborting job" % (self.tid, out))
        
        with open(out, "w") as f:
            if self.state["InputType"] == "OptionList":
                for line in Job.copy_from_lines:
                    sline = line.split()
                    if len(sline) > 1 and sline[0] in copy_list and sline[1] == sep:
                        f.write("%s %s %s\n" % (sline[0], sep, self.state[sline[0]]))
                        copy_list.remove(sline[0])
                        Logger.log("Job %d: overwriting %s" % (self.tid, sline[0]), Logger.DEBUG)
                    else:
                        f.write(line)
    
                for k in copy_list:
                    f.write("%s %s %s\n" % (k, sep, self.state[k]))
            elif self.state["InputType"] == "LAMMPS":
                for line in Job.copy_from_lines:
                    sline = line.split()
                    if len(sline) > 2 and sline[0] == "variable" and sline[1] in copy_list:
                        f.write("variable %s equal %s\n" % (sline[1], self.state[sline[1]]))
                        copy_list.remove(sline[1])
                        Logger.log("Job %d: overwriting %s" % (self.tid, sline[1]), Logger.DEBUG)
                    else:
                        f.write(line)
                        
                if len(copy_list) != 0:
                    Logger.log("Job %d: keys '%s' have not been found in the original input file and hence have not been used" % (self.tid, " ".join(copy_list)), Logger.WARNING)
            elif self.state["InputType"] == "Jinja2":
                j_env = jinja2.Environment()
                try:
                    j_template = j_env.from_string("\n".join(Job.copy_from_lines))
                except jinja2.exceptions.TemplateError as e:
                    Logger.log("Job %d: jinja2 raised the following error: '%s'" % e.message, Logger.CRITICAL)
                    exit(1)
                key_dict = dict((key, self.state[key]) for key in copy_list)
                f.write(j_template.render(key_dict))
                    

    # also set self.working_dir
    def create_dir_structure(self):
        if "DirectoryStructure" in self.state:
            self.working_dir = os.path.join(self.original_dir, self.state['DirectoryStructure'])
            if not os.path.exists(self.working_dir):
                os.makedirs(self.working_dir)
            elif self.safe:
                raise Job.SafeError("Job %d: can't overwrite directory '%s' in safe mode, aborting job" % (self.tid, self.working_dir))

        if "Subdirectories" in self.state:
            subdirs = self.state['Subdirectories'].split()

            for sdir in subdirs:
                totdir = os.path.join(self.working_dir, sdir)
                if not os.path.exists(totdir):
                    os.makedirs(totdir)

    def copy_objects(self):
        if "CopyObjects" not in self.state:
            return

        objs = self.state['CopyObjects'].split()

        for obj in objs:
            # this one-liner should be enough to discriminate between relative and absolute paths
            obj = os.path.join(self.original_dir, obj)
            try:
                if os.path.isdir(obj):
                    # the dst in copytree may not exist so we have to give it the current dir + the name
                    # of the folder we want to copy
                    name = os.path.basename(os.path.normpath(obj))
                    shutil.copytree(obj, os.path.join(self.working_dir, name))
                else:
                    shutil.copy(obj, self.working_dir)
            except Exception as e:
                Logger.log("Job %d: caught an error while trying to copy '%s': %s" % (self.tid, obj, e), Logger.WARNING)

    def is_directory_used(self):
        if self.relative_dir in Job.dir_taken:
            return Job.dir_taken[self.relative_dir]
        else:
            return False

    def _execute(self, cmd):
        # we need a lock because we have to change the current directory
        Job.dir_lock.acquire()
        
        os.chdir(self.working_dir)
        
        p = subprocess.Popen(cmd, shell=True, cwd=self.working_dir)
        
        os.chdir(self.original_dir)

        Job.dir_lock.release()

        _, status = os.waitpid(p.pid, 0)
        
        return os.WEXITSTATUS(status)

    def run(self):
        while True:
            self.state = Job.queue.get(True)

            if "DirectoryStructure" in self.state:
                self.relative_dir = self.state['DirectoryStructure']
            else:
                self.relative_dir = "."

            if self.state["Exclusive"] == "True":
                self.dir_taken_lock.acquire()
                run = not self.is_directory_used()
                if run:
                    Job.dir_taken[self.relative_dir] = True
                self.dir_taken_lock.release()
            else:
                run = True

            if run:
                try:
                    self.create_dir_structure()
                    self.create_copy_to()
                    self.copy_objects()
                except Job.SafeError as e:
                    Logger.log(e, Logger.WARNING)
                    if Job.dir_lock.locked():
                        Job.dir_lock.release()
                else:
                    pre_exit_code = 0
                    if self.state["PreExecute"] != "":
                        pre_exit_code = self._execute(self.state["PreExecute"])
                            
                    if pre_exit_code == 0:
                        relaunch = "Relaunch" in self.state and self.state["Relaunch"] == "True"
                        execute = True
                        exit_code = 0
                        while execute:
                            exit_code = self._execute(self.state["Execute"])
                            # if Relaunch is True then we relaunch the process if its previous exit code was non-zero
                            execute = relaunch and exit_code != 0
                            
                        if exit_code == 0:
                            if self.state["PostExecute"] != "":
                                post_exit_code = self._execute(self.state["PostExecute"])
                                if post_exit_code != 0:
                                    Logger.log("Job %d: the PostExecute command '%s' returned %d" % (self.tid, self.state["PreExecute"], post_exit_code), Logger.ERROR)
                    else:
                        Logger.log("Job %d: the PreExecute command '%s' returned %d" % (self.tid, self.state["PreExecute"], pre_exit_code), Logger.ERROR)
                        
                if self.state["Exclusive"] == "True":
                    self.dir_taken_lock.acquire()
                    Job.dir_taken[self.relative_dir] = False
                    self.dir_taken_lock.release()

            Job.queue.task_done()


class StateFactory(object):
    def __init__(self, values, modifiers):
        self.values = list(values)
        self.modifiers = list(modifiers)
        self.last_val = len(self.values) - 1
        self.changing_key = self.last_val
        self.max_changed = self.last_val
        self.first = True
        self.current_id = 0

        self.order_by_dependencies()

        for v in self.values:
            v.expand()

    def get_constant_keys(self):
        return [k for k in self.values if type(k) == BaseKey and not k.has_modifiers()]

    # we need to order values by dependency because otherwise we would end up with 
    # unpredictable states
    def order_by_dependencies(self):
        # we split the values according to their dependencies: nodep will contain 
        # those keys that do not depend on anything while with dep will contain, in 
        # a ordered mode, all the keys that depend on other keys
        nodep = []
        withdep = []
        for i in range(len(self.values)):
            val = self.values[i]
            if not val.has_dependencies():
                nodep.append(val)
            else:
                found = False
                for j in range(len(withdep)):
                    if withdep[j].depends_on(val.key):
                        withdep.insert(j, val)
                        found = True
                        break

                if not found:
                    withdep.append(val)

        self.values = nodep + withdep

    def get_state_dict(self):
        state = {}

        # first we generate the default state dictionary
        for v in self.values:
            if v.key == "JOB_ID":
                v.raw_value = str(self.current_id)
            v.expand()
            state[v.key] = v()

        return state

    def set_next(self):
        if not self.first:
            self.current_id += 1
            changed = False
            # in this loop we cycle through all the values of the keys
            while not changed:
                if self.values[self.changing_key].set_next_value():
                    changed = True

                    if self.max_changed >= self.changing_key:
                        self.changing_key = self.last_val
                        self.max_changed = self.changing_key
                else:
                    self.changing_key -= 1

                if self.max_changed < 0 or self.changing_key < 0:
                    return False

        self.first = False
        return True


class Launcher(object):
    def __init__(self, inp):
        self.states = []
        self.num_states = 0

        # default values
        self.max_jobs = 0
        self.waiting_time = 2.0

        self.copy_from = None
        self.copy_from_lines = None

        self.times = 1

        self.inp_parser = KeyValueDict(inp)
        self.inp_parser.parse()

        self.get_global_options()
        if self.copy_from is not None:
            self.read_copy_from()

    def read_copy_from(self):
        if not os.path.isfile(self.copy_from):
            Logger.log("CopyFrom file '%s' not found" % self.copy_from, Logger.CRITICAL)
            exit(1)

        with open(self.copy_from) as f:
            self.copy_from_lines = f.readlines()

        if self.inp_parser["InputType"]() == "Jinja2":
            j_env = jinja2.Environment()
            try:
                j_env.from_string("\n".join(self.copy_from_lines))
            except jinja2.exceptions.TemplateSyntaxError as e:
                Logger.log("jinja2 raised the following syntax error: '%s' at line %d" % (e.message, e.lineno), Logger.CRITICAL)
                exit(1)
            except jinja2.exceptions.TemplateError as e:
                Logger.log("jinja2raised the following error: '%s'" % e.message, Logger.CRITICAL)
                exit(1)

    def get_global_options(self):
        if "ContemporaryJobs" in self.inp_parser:
            self.max_jobs = int(self.inp_parser.pop("ContemporaryJobs")())

        if "Times" in self.inp_parser:
            self.times = int(self.inp_parser.pop("Times")())

        if "CopyFrom" in self.inp_parser:
            self.copy_from = self.inp_parser["CopyFrom"]()

        if "WaitingTime" in self.inp_parser:
            self.waiting_time = float(self.inp_parser.pop("WaitingTime")())

    def print_run_info(self, state, complete):
        basekeys = state.get_constant_keys()
        my_format = "\t%s: %s"
        # the JOB_ID key is different from any other key, as it is considered to be immutable by pyrla but it is not
        formatted_basekeys = [my_format % (k.key, k.value) for k in basekeys if k.key != "JOB_ID"]

        print("\nRUN INFO:")
        print("Number of processes: %d" % self.num_states)
        print("Contemporary processes: %d" % self.max_jobs)
        print("Waiting time between job launches: %f" % self.waiting_time)
        if self.times > 1:
            print("Each job will be repeated %d times" % self.times)
        if self.copy_from != None:
            print("The input file will be based on '%s'" % self.copy_from)
        print("\nKEYS WITH FIXED VALUES")
        print("\n".join(formatted_basekeys))
        
        if complete:
            for i in range(len(self.states)):
                print("\nJOB %d" % i)
                for k, v in self.states[i].items():
                    to_print = my_format % (k, v)
                    if to_print not in formatted_basekeys:
                        print(to_print)

    def launch(self, opts):
        state = StateFactory(list(self.inp_parser.values()), self.inp_parser.modifiers)

        while state.set_next() != False:
            self.states.append(state.get_state_dict())
            self.num_states += 1

            if self.num_states > opts['max_states']:
                Logger.log("The number of states exceeds the maximum number %d" % opts['max_states'], Logger.CRITICAL)
                exit(1)
                
        if self.max_jobs > self.num_states or self.max_jobs == 0:
            self.max_jobs = self.num_states

        if opts['dry_run'] or opts['summarise']:
            self.print_run_info(state, opts['dry_run'])
            return
        
        if opts['wait'] > 0:
            import time
            time.sleep(opts['wait'])

        if self.copy_from is not None:
            Job.copy_from_lines = self.copy_from_lines

        for i in range(self.max_jobs):
            j = Job(i, opts['safe'])
            j.setDaemon(True)
            j.start()

        end_at = self.num_states
        if opts['end_after'] is not None:
            end_at = opts['start_from'] + opts['end_after']
            if end_at > self.num_states:
                end_at = self.num_states

        for j in range(self.times):
            for i in range(opts['start_from'], end_at):
                Logger.log("State n.%d: " % i + str(self.states[i]), Logger.DEBUG)
                Job.queue.put(self.states[i], block=True)
                sleep(self.waiting_time)

        Job.queue.join()


def main():
    def print_usage():
        print("USAGE:")
        print("\t%s input [-d|--debug] [-h|--help] [-v|--version]" % sys.argv[0])
        print("\t[-r|--dry-run] [-s|--safe] [--max-states N] [--start-from N] [--end-after N]")
        print("\t[-S\--summarise] [-w\--wait seconds]")
        exit(1)

    def print_version():
        print("pyrla (PYrla è un Rivoluzionario Lanciatore Asincrono) 0.0.3")
        print("Copyright (C) 2011 Lorenzo Rovigatti")
        print("This is free software; see the source for copying conditions.  There is NO")
        print("warranty; not even for MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.\n")
        exit(1)
        
    def parse_options(command_line_args):
        shortArgs = 'dhvrsSw:'
        longArgs = ['debug', 'help', 'version', 'dry-run', 'safe', 'max-states=', 'start-from=', 'end-after=', 'summarise', 'wait=']
        # by default we do not want to output messages marked with the Logger.DEBUG flag
        Logger.debug_level = 1
        opts = {
                'dry_run' : False,
                'summarise' : False,
                'safe' : False,
                'max_states' : MAX_STATES,
                'start_from' : 0,
                'end_after' : None,
                'wait' : 0
                }
    
        import getopt
        args, files = getopt.gnu_getopt(command_line_args, shortArgs, longArgs)
        
        if len(files) == 0:
            raise Exception("Mandatory input file missing")
        
        if len(files) > 1:
            raise Exception("There should be a single input file, found %d" % len(files))
        
        for k in args:
            if k[0] == '-d' or k[0] == '--debug': 
                Logger.debug_level = 0
            if k[0] == '-h' or k[0] == '--help': 
                print_usage()
            if k[0] == '-v' or k[0] == '--version': 
                print_version()
            if k[0] == '-r' or k[0] == '--dry-run': 
                opts['dry_run'] = True
            if k[0] == '-S' or k[0] == '--summarise':
                opts['summarise'] = True
            if k[0] == '-s' or k[0] == '--safe': 
                opts['safe'] = True
            if k[0] == '-w' or k[0] == '--wait':
                opts['wait'] = int(k[1]) 
            if k[0] == '--start-from': 
                opts['start_from'] = int(k[1])
            if k[0] == '--end-after': 
                opts['end_after'] = int(k[1])
            if k[0] == '--max-states': 
                opts['max_states'] = int(k[1])
                
        if opts['dry_run'] and opts['summarise']:
            raise Exception("Summarise (-S/--summarise) and dry-run (-r/--dry-run) are incompatible")

        return opts, files[0]
    try:
        opts, inp = parse_options(sys.argv[1:])
    except Exception as e:
        Logger.log(e, Logger.ERROR)
        print_usage()

    launcher = Launcher(inp)
    launcher.launch(opts)

if __name__ == '__main__':
    main()
