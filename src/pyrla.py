#!/usr/bin/env python
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
#    - add PreExecute and PostExecute (executed by each job)
#    - add PreJobsLaunch and PostJobsLaunch (executed at a 'global' level 
#        before and after the spawning of the threads)
#-------------------------------------------------------------------------------- 

import sys
import re
import threading
import Queue
import os
import subprocess
import shutil
from time import sleep
# used to process mathematical expressions
from math import *

MAX_STATES = 100000

# static class
class Logger():
    debug_level = 0
    DEBUG = 0
    INFO = 1
    WARNING = 2
    CRITICAL = 3

    messages = ("DEBUG", "INFO", "WARNING", "CRITICAL")

    @staticmethod
    def log(msg, level):
        if level < Logger.debug_level: return

        print "%s: %s" % (Logger.messages[level], msg)


class BaseKey(object):
    SPECIAL_KEYS = ("CopyTo", "CopyFrom", "CopyToWrite", "Execute", "DirectoryStructure",
                    "ContemporaryJobs", "Subdirectories", "CopyObjects", "WaitingTime",
                    "Times", "InputSeparator", "Exclusive", "SwapSUS", "LastFile")

    def __init__(self, key, value):
        self.key = key
        self.raw_value = value
        if self.raw_value[0] == '"' and self.raw_value[-1] == '"':
            self.raw_value = self.raw_value[1:-1]
        self.value = self.raw_value
        # special keys (aka keywords like Input, DirectoryStructure, ecc) need to be handled in a different way
        self.special = (self.key in BaseKey.SPECIAL_KEYS)

    def __cmp__(self, other):
        if other.depends_on(self.key): return - 1
        elif self.depends_on(other.key): return 1
        else:
            ih = self.has_dependencies()
            oh = other.has_dependencies()
            if ih and not oh: return 1
            elif oh and not ih: return - 1

            return 0

    # returns False if there is no next value
    def set_next_value(self):
        return False

    def has_dependencies(self):
        return False

    def depends_on(self, key):
        return False

    def is_iterable(self):
        return (type(self.value) == list)

    def __call__(self):
        return self.value

    def __repr__(self):
        return "%s: %s = %s" % (self.__class__.__name__, self.key, self())

    def expand(self):
        self.value = self.raw_value


class MultipleKey(BaseKey):
    def __init__(self, key, value):
        BaseKey.__init__(self, key, value)
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

    def expand(self):
        if self.special == False: self.value = self.raw_value.split()
        else: self.value = [self.raw_value, ]
        
        
class FileKey(MultipleKey):
    RE = "^LF"
    
    def __init__(self, key, value):
        filename = value[2:].strip()
        try:
            inp = open(filename, "r")
            loaded_value = " ".join(inp.readlines())
            inp.close()
        except IOError:
            Logger.log("File '%s' not found" % filename, Logger.CRITICAL)
            exit(1)
        
        MultipleKey.__init__(self, key, loaded_value)
        
        
class ExpressionKey(BaseKey):
    def __init__(self, key, value, other_keys, other_values):
        BaseKey.__init__(self, key, value)
        self.other_keys = other_keys
        self.other_values = other_values
        self.depends_on_keys = []

        self.get_dependencies()

    # this is a recursive function: if A depends on B and B depends on C
    # then A.depends_on(C) will return True
    def depends_on(self, key):
        if key in self.depends_on_keys: return True
        for k in self.depends_on_keys:
            try:
                index = self.other_keys.index(k)
            except ValueError:
                Logger.log("Key '%s' (which is expanded by '%s') is not defined" % (k, self.key), Logger.CRITICAL)
                exit(1)
            if self.other_values[index].depends_on(key): return True

        return False

    def has_dependencies(self):
        return (len(self.depends_on_keys) > 0)

    def get_dependencies(self):
        found_keys = re.findall('\$\([\w\[\]]+\)' , self.raw_value)

        for fk in found_keys:
            # we have to get rid of $( and )
            key = fk[2:-1]
            self.depends_on_keys.append(key)

    def expand_variables(self):
        # expand the variables found by get_dependencies
        for key in self.depends_on_keys:
            try:
                index = self.other_keys.index(key)
                other_v = self.other_values[index]
                if other_v.depends_on(self.key):
                    Logger.log("Circular dependency between '%s' and '%s', aborting" % (self.key, key), Logger.CRITICAL)
                    exit(1)

                dep_value = other_v()

                self.value = self.value.replace("$(%s)" % key, dep_value)
            except Exception as e:
                Logger.log("Can't expand variable '%s' in line '%s' (error: %s)" % (key, self.raw_value, e), Logger.WARNING)

    def expand_math(self):
        # expand mathematical expressions
        found_maths = re.findall('\$\{.*?\}' , self.value)

        for mk in found_maths:
            try:
                # we have to get rid of ${ and }
                res = eval(mk[2:-1])
                self.value = self.value.replace(mk, str(res))
            except Exception as e:
                Logger.log("Can't expand mathematical expression '%s' in line '%s' (error: %s)" % (mk, self.raw_value, e), Logger.WARNING)

    def expand(self):
        self.value = self.raw_value

        self.expand_variables()
        self.expand_math()


class BashKey(ExpressionKey):
    RE = '^\$b\{.*?\}$'
    
    def __init__(self, key, value, other_keys, other_values):
        ExpressionKey.__init__(self, key, value, other_keys, other_values)
        
    def expand(self):
        ExpressionKey.expand(self)
        found_keys = re.findall(BashKey.RE , self.value)
        if len(found_keys) != 1:
            Logger.log("Can't expand variable '%s' in line '%s' (error: bash commands should be enclosed between '$b{' and '}')" % (self.key, self.raw_value), Logger.WARNING)
        else:
            command = found_keys[0][3:-1]
            p = subprocess.Popen(command, stdout=subprocess.PIPE, shell=True)
            out = p.communicate()[0]
            self.value = out.strip()


class ExpressionMultipleKey(MultipleKey, ExpressionKey):
    RE = "^F([\s]+.*?[\s]+)T([\s]+.*?[\s]+)V([\s]+.*?[\s]*)$"

    def __init__(self, key, value, other_keys, other_values):
        MultipleKey.__init__(self, key, value)
        ExpressionKey.__init__(self, key, value, other_keys, other_values)

    def expand_complex_math(self):
        compl_found = re.findall(ExpressionMultipleKey.RE, self.value)[0]

        if len(compl_found) != 3:
            Logger.log("Can't expand complex mathematical expression in line '%s' (error: malformed line)" % (self.raw_value), Logger.CRITICAL)
            exit(1)

        self.value = []
        next_v = float(compl_found[0])
        target = float(compl_found[1])
        old_dist = fabs(next_v - target)
        if next_v <= target: condition = lambda test, tar: test < tar
        else: condition = lambda test, tar: test > tar

        end = False
        while not end:
            # this is a (dirty) way to understand if next_v is (or the user wants it to be) an integer or not
            if fabs(next_v - round(next_v)) < 1e-6: next_v = int(round(next_v))
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


    def expand(self):
        ExpressionKey.expand(self)
        self.expand_complex_math()


class InputParser(object):
    REQUIRED_BASEKEYS = ("CopyFrom", "ContemporaryJobs")
    PROTECTED_KEYS = ("JOB_ID", "BASE_DIR")

    def __init__(self, inp):
        self.input = inp
        
        self.keys = ["JOB_ID", "BASE_DIR"]
        self.values = [
                       MultipleKey("JOB_ID", "-1"),
                       BaseKey("BASE_DIR", os.getcwd())
                       ]

        if not os.path.isfile(inp):
            Logger.log("Input file '%s' not found" % inp, Logger.CRITICAL)
            exit(1)

    def check(self):
        if not "Execute" in self.keys:
            Logger.log("Mandatory key 'Execute' missing", Logger.CRITICAL)
            exit(1)

        if "SwapSUS" in self.keys:
            if not "DirectoryStructure" in self.keys:
                Logger.log("Mandatory key 'DirectoryStructure' is missing", Logger.CRITICAL)
                exit(1)

            if not "LastFile" in self.keys:
                Logger.log("Mandatory key 'LastFile' is missing", Logger.CRITICAL)
                exit(1)

            if "Exclusive" in self.keys:
                excl = self.pop("Exclusive")
            else: excl = False

            if not excl: Logger.log("'SwapSUS = True' implies 'Exclusive = True'", Logger.WARNING)

            self.keys.append("Exclusive")
            self.values.append(BaseKey("Exclusive", "True"))

        if not "Exclusive" in self.keys:
            self.keys.append("Exclusive")
            self.values.append(BaseKey("Exclusive", "False"))
        else:
            ind = self.keys.index("Exclusive")
            self.values[ind].raw_value = self.values[ind].raw_value.capitalize()

        for bk in InputParser.REQUIRED_BASEKEYS:
            if self.has_key(bk):
                if self.key(bk).__class__.__name__ != BaseKey.__name__:
                    Logger.log("The key '%s' may not be a list nor contain expressions" % bk, Logger.CRITICAL)
                    exit(1)


    def has_key(self, key):
        return key in self.keys

    def key(self, key):
        ind = self.keys.index(key)
        return self.values[ind]

    def pop(self, key):
        ind = self.keys.index(key)
        self.keys.pop(ind)
        return self.values.pop(ind)

    def parse(self):
        with open(self.input) as f:
            for line in f.readlines():
                self.fill_lists(line)

        self.check()

    def fill_lists(self, line):
        s_line = line.strip()
        if len(s_line) > 0:
            my_list = s_line.partition('=')
            if my_list[0][0] != '#':
                if my_list[1] == '':
                    Logger.log("Malformed line '%s'" % s_line, Logger.WARNING)
                    return

                key = my_list[0].strip()
                if key in InputParser.PROTECTED_KEYS:
                    Logger.log("'%s' is a protected keyword and cannot be used as a key" % key, Logger.CRITICAL)
                    exit(1)
                    
                if key in self.keys:
                    Logger.log("Key '%s' is defined more than once, I'll use the first definition only (trashing '%s')"
                               % (key, my_list[2].strip()), Logger.WARNING)
                    return

                self.keys.append(key)
                self.values.append(self.select_right_key(key, my_list[2].strip()))

    def select_right_key(self, key, value):
        if re.search(ExpressionMultipleKey.RE, value) != None:
            # if value contains the special keyword F T and V then it's a MultipleExpressionKey
            return ExpressionMultipleKey(key, value, self.keys, self.values)
        elif re.search(FileKey.RE, value) != None:
            return FileKey(key, value)
        elif re.search(BashKey.RE, value) != None:
            return BashKey(key, value, self.keys, self.values)
        elif "$(" in value or "${" in value:
            return ExpressionKey(key, value, self.keys, self.values)
        else:
            if value[0] == '"' and value[-1] == '"' or len(value.split()) == 1:
                return BaseKey(key, value)
            else: return MultipleKey(key, value)


# our worker!
class Job(threading.Thread):

    class SafeError(Exception):
        def __init__(self, value):
            self.value = value
        def __str__(self):
            return self.value

    queue = Queue.Queue(1)
    dir_lock = threading.Lock()
    dir_taken = {}
    dir_taken_lock = threading.Lock()
    # contains lines of the original copy_from file
    copy_from_lines = None

    def __init__(self, tid, safe):
        threading.Thread.__init__(self)
        self.tid = tid
        self.original_dir = os.getcwd()
        self.working_dir = os.getcwd()
        self.safe = safe

    def create_copy_to(self):
        if "CopyFrom" not in self.state: return

        sep = self.state["InputSeparator"] if "InputSeparator" in self.state else "="

        if "CopyTo" in self.state: name = self.state['CopyTo']
        else: name = self.state['CopyFrom']

        # with list(set(*)) we are sure that copy_list contains only unique elements
        if "CopyToWrite" in self.state: copy_list = list(set(self.state['CopyToWrite'].split()))
        else: copy_list = []

        copy_not_found = []
        for k in copy_list:
            if k not in self.state:
                copy_list.remove(k)
                copy_not_found.append(k)

        if len(copy_not_found) != 0:
            Logger.log("Job %d: keys '%s' are in CopyToWrite but are not defined" % (self.tid, " ".join(copy_not_found)), Logger.WARNING)

        out = self.working_dir + "/" + name
        if self.safe and os.path.exists(out):
            raise Job.SafeError("Job: %d: can't overwrite file '%s' in safe mode, aborting job" % (self.tid, out))

        with open(out, "w") as f:
            for line in Job.copy_from_lines:
                sline = line.split()
                if len(sline) > 1 and sline[0] in copy_list and sline[1] == sep:
                    f.write("%s %s %s\n" % (sline[0], sep, self.state[sline[0]]))
                    copy_list.remove(sline[0])
                    Logger.log("Job %d: overwriting %s" % (self.tid, sline[0]), Logger.DEBUG)
                else: f.write(line)

            for k in copy_list:
                f.write("%s %s %s\n" % (k, sep, self.state[k]))

    # also set self.working_dir
    def create_dir_structure(self):
        if "DirectoryStructure" in self.state:
            self.working_dir = self.original_dir + "/" + self.state['DirectoryStructure']
            if not os.path.exists(self.working_dir): os.makedirs(self.working_dir)
            elif self.safe:
                raise Job.SafeError("Job: %d: can't overwrite directory '%s' in safe mode, aborting job" % (self.tid, self.working_dir))

        if "Subdirectories" in self.state:
            subdirs = self.state['Subdirectories'].split()

            for sdir in subdirs:
                totdir = self.working_dir + "/" + sdir
                if not os.path.exists(totdir): os.makedirs(totdir)

    def copy_objects(self):
        if "CopyObjects" not in self.state: return

        objs = self.state['CopyObjects'].split()

        for obj in objs:
            # this one-liner should be enough to discriminate between relative and absolute paths
            obj = os.path.join(self.original_dir, obj)
            try:
                if os.path.isdir(obj):
                    # the dst in copytree may not exist so we have to give it the chdir + the name
                    # of the folder we want to copy
                    name = os.path.basename(os.path.normpath(obj))
                    shutil.copytree(obj, self.working_dir + "/" + name)
                else: shutil.copy(obj, self.working_dir)
            except Exception as e:
                Logger.log("Job %d: caught an error while trying to copy '%s': %s" % (self.tid, obj, e), Logger.WARNING)

    def is_directory_used(self):
        if self.relative_dir in Job.dir_taken:
            return Job.dir_taken[self.relative_dir]
        else: return False

    def get_N_from_conf(self, name):
        with open(name) as f:
            return int(f.readline().split()[2])

    def run(self):
        while True:
            self.state = Job.queue.get(True)

            if "DirectoryStructure" in self.state:
                self.relative_dir = self.state['DirectoryStructure']
            else: self.relative_dir = "."

            if self.state["Exclusive"] == "True":
                self.dir_taken_lock.acquire()
                run = not self.is_directory_used()
                if run: Job.dir_taken[self.relative_dir] = True
                self.dir_taken_lock.release()
            else: run = True

            if run:
                # we need a lock because we have to change the current directory
                Job.dir_lock.acquire()

                try:
                    self.create_dir_structure()
                    self.create_copy_to()
                    self.copy_objects()
                except Job.SafeError as e:
                    Logger.log(e, Logger.WARNING)
                    Job.dir_lock.release()
                else:
                    os.chdir(self.working_dir)

                    p = subprocess.Popen(self.state["Execute"], shell=True, cwd=self.working_dir)
                    os.chdir(self.original_dir)

                    if "NextDirectoryStructure" in self.state:
                        last = self.state["LastFile"]
                        last_here = os.path.join(self.state['DirectoryStructure'], last)
                        last_next = os.path.join(self.state['NextDirectoryStructure'], last)

                        # this fails if the directory structure has not been setup yet
                        try:
                            swap_log = open(os.path.join(self.state['DirectoryStructure'], "swap_log.dat"), "a")

                            N_here = self.get_N_from_conf(last_here)
                            N_next = self.get_N_from_conf(last_next)

                            if N_here == N_next:
                                os.rename(last_here, last_next + ".tmp")
                                os.rename(last_next, last_here)
                                os.rename(last_next + ".tmp", last_next)
                                swap_log.write("1\n")
                            else:
                                swap_log.write("0\n")

                            swap_log.close()
                        except IOError:
                            pass

                    Job.dir_lock.release()

                    os.waitpid(p.pid, 0)

                if self.state["Exclusive"] == "True":
                    self.dir_taken_lock.acquire()
                    Job.dir_taken[self.relative_dir] = False
                    self.dir_taken_lock.release()

            Job.queue.task_done()


class StateFactory(object):
    def __init__(self, values):
        self.values = list(values)
        self.last_val = len(self.values) - 1
        self.changing_key = self.last_val
        self.max_changed = self.last_val
        self.first = True
        self.current_id = 0

        self.order_by_dependencies()

        for i in range(len(self.values)):
            self.values[i].expand()

    def get_basekeys(self):
        return [k for k in self.values if type(k) == BaseKey]

    # we need to order values by dependency because otherwise we would end up with 
    # unpredictable states
    def order_by_dependencies(self):
        # first we split the values: nodep will contain keys that not depend on anything
        # while with dep will contain, in a ordered mode, all the keys that depend on
        # other keys
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

                if not found: withdep.append(val)

        self.values = nodep + withdep

    def get_state_dict(self):
        state = {}

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

                if self.max_changed < 0 or self.changing_key < 0: return False

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

        self.swap_sus = False

        self.times = 1

        self.inp_parser = InputParser(inp)
        self.inp_parser.parse()

        self.get_global_options()
        if self.copy_from != None:
            self.read_copy_from()

    def read_copy_from(self):
        if not os.path.isfile(self.copy_from):
            Logger.log("CopyFrom file '%s' not found" % self.copy_from, Logger.CRITICAL)
            exit(1)

        with open(self.copy_from) as f:
            self.copy_from_lines = f.readlines()

    def get_global_options(self):
        if self.inp_parser.has_key("ContemporaryJobs"):
            self.max_jobs = int(self.inp_parser.pop("ContemporaryJobs")())

        if self.inp_parser.has_key("Times"):
            self.times = int(self.inp_parser.pop("Times")())

        if self.inp_parser.has_key("CopyFrom"):
            self.copy_from = self.inp_parser.key("CopyFrom")()

        if self.inp_parser.has_key("SwapSUS"):
            self.swap_sus = self.inp_parser.key("SwapSUS")()

        if self.inp_parser.has_key("WaitingTime"):
            self.waiting_time = float(self.inp_parser.pop("WaitingTime")())

    def print_run_info(self, state):
        basekeys = state.get_basekeys()
        my_format = "\t%s: %s"
        formatted_basekeys = [my_format % (k.key, k.value) for k in basekeys]

        print "\nRUN INFO:"
        print "Number of processes: %d" % self.num_states
        print "Contemporary processes: %d" % self.max_jobs
        print "Waiting time between job launches: %d" % self.waiting_time
        if self.times > 1: print "Each job will be repeated %d times" % self.times
        if self.copy_from != None:
            print "Input file will be based on '%s'" % self.copy_from
        print "\nKEYS WITH FIXED VALUES"
        print "\n".join(formatted_basekeys)

        for i in range(len(self.states)):
            print "\nJOB %d" % i
            for k, v in self.states[i].iteritems():
                toprint = my_format % (k, v)
                if toprint not in formatted_basekeys: print toprint

    def launch(self, opts):
        state = StateFactory(self.inp_parser.values)

        while state.set_next() != False:
            self.states.append(state.get_state_dict())
            self.num_states += 1

            if self.swap_sus and self.num_states > 1:
                self.states[-2]["NextDirectoryStructure"] = self.states[-1]["DirectoryStructure"]

            if self.num_states > opts['max_states']:
                Logger.log("The number of states exceeds the maximum number %d" % opts['max_states'], Logger.CRITICAL)
                exit(1)

        if self.max_jobs > self.num_states or self.max_jobs == 0:
            self.max_jobs = self.num_states

        if opts['dry_run'] == True:
            self.print_run_info(state)
            return

        if self.copy_from != None:
            Job.copy_from_lines = self.copy_from_lines

        for i in range(self.max_jobs):
            j = Job(i, opts['safe'])
            j.setDaemon(True)
            j.start()

        end_at = self.num_states
        if opts['end_after'] != None: 
            end_at = opts['start_from'] + opts['end_after']
            if end_at > self.num_states: end_at = self.num_states

        for j in range(self.times):
            for i in range(opts['start_from'], end_at):
                Logger.log("State n.%d: " % i + str(self.states[i]), Logger.DEBUG)
                Job.queue.put(self.states[i], block=True)
                sleep(self.waiting_time)

        Job.queue.join()


def main():
    def print_usage():
        print "USAGE:"
        print "\t%s input [-d|--debug] [-h|--help] [-v|--version]" % sys.argv[0]
        print "\t[-r|--dry-run] [-s|--safe] [--max-states N] [--start-from N] [--end-after N]"
        exit(1)

    def print_version():
        print "pyrla (PYrla è un Rivoluzionario Lanciatore Asincrono) 0.0.3"
        print "Copyright (C) 2011 Lorenzo Rovigatti"
        print "This is free software; see the source for copying conditions.  There is NO"
        print "warranty; not even for MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.\n"
        exit(1)

    if len(sys.argv) < 2:
        print_usage()
        exit(1)

    shortArgs = 'dhvrs'
    longArgs = ['debug', 'help', 'version', 'dry-run', 'safe', 'max-states=', 'start-from=', 'end-after=']
    debug = 1
    opts = {
            'dry_run' : False,
            'safe' : False,
            'max_states' : MAX_STATES,
            'start_from' : 0,
            'end_after' : None
            }

    try:
        import getopt
        args, files = getopt.gnu_getopt(sys.argv[1:], shortArgs, longArgs)
        for k in args:
            if k[0] == '-d' or k[0] == '--debug': debug = 0
            if k[0] == '-h' or k[0] == '--help': print_usage()
            if k[0] == '-v' or k[0] == '--version': print_version()
            if k[0] == '-r' or k[0] == '--dry-run': opts['dry_run'] = True
            if k[0] == '-s' or k[0] == '--safe': opts['safe'] = True
            if k[0] == '--start-from': opts['start_from'] = int(k[1])
            if k[0] == '--end-after': opts['end_after'] = int(k[1])
            if k[0] == '--max-states': opts['max_states'] = int(k[1])

        inp = files[0]
    except Exception as e:
        print e
        print_usage()

    Logger.debug_level = debug

    launcher = Launcher(inp)
    launcher.launch(opts)

if __name__ == '__main__':
    main()