# pyrla

pyrla makes it easy to launch parallel processes that execute different commands. Its most common use case is having to run the same command in different directories ordered in a specific hierarchy (e.g. `Temperature_T/Pressure_P`, for several values of `P` and `T`). Perhaps the command should be invoked with folder-specific parameters. pyrla makes it easier to automatise this type of repetitive operations without having to resort to bash scripts or similar means. 
With pyrla, you can choose the number of contemporary jobs and their working path, which can be automatically generated. 
If the command you want to execute takes an input file as an argument (or if you want to have a bespoke file in each job's current directory), such an input file can be written on the fly or generated from an existent input file.
	
## Usage

pyrla expects a single input file (see [Input file syntax](#input-file-syntax)). It also supports the following options:

	-d, --debug 
		enable debug (verbose) mode. Useful for developers
	--ends-after n
		run the first n jobs only
	-h, --help
		show a usage message
	--max-states n
		set the maximum number of states (jobs) that can be generated. Defaults to 100000
	-r, --dry-run
		show a complete summary of the jobs that will run. Useful for testing input files
	-S, --summarise
		show a synthetic summary of the run
	-s, --safe
		enable safe mode. No file or directory will be overwritten
	--start-from n
		start jobs having an id >= n
	-v, --version
		show the version of the program
	-w, --wait n
		wait n seconds before starting the jobs (after the parsing of the input file)

## Examples

The `pyrla/examples/` folder contains commented pyrla input files that can be used as starting points to build your own.

## Input file syntax

* Empty lines or lines starting with a hash sign (\#) will not be considered. A well-formed line should look like 'key = value'. Spaces before and after key and value are stripped off.
* Any text coming after a hash sign (\#) will be discarded.
* About the 'value' syntax:
	* in general if your value contains spaces then it will be considered as a 'special' value (a mathematical expression or a list of values, for examples). If you want to avoid this you have to put double quotes (") around the whole value.
	* you can refer to other values by using the syntax $(key). The value of 'key' will be expanded at runtime. An example would be `T_$(T)`.
	* you can use mathematical expressions but you have to put them between ${ and }. An example would be `${2 + 3}`. You can also use complex functions (as long as they are defined in python's math module). An example would be `${log($(T)) + 0.2}`.
	* you can load a list of values from a file by using the syntax `key = LF filename`. Each row will be treated as an item of the list.
	* you can use complex sequences in a way similar to bash's seq or python's range but in a more flexible way. The actual syntax is: `F start T target V inc`. Of course start is the starting value while target is the final value (excluded from the sequence, like in C-style for loops) and inc is the action to be performed on start to go towards target. A simple example would be `T = F 0.1 T 0.4 V +0.1` which is equivalent `T = 0.1 0.2 0.3`. You can also have more complex sequences like `T = F 0.1 T 100 V \*10`, which is equivalent to `T = 0.1 1 10`.
	* you can evaluate a bash command and assign its value to a pyrla variable by enclosing the command between $b{ and }. For example, `a = $b{echo "prova"}` would assign the value 'prova' to the key 'a' 
		
* There are some special keys used as 'keywords'. These are:
	* `DirectoryStructure`: structure of the directory where the `Execute` command should be executed. It can depend on other variables (for example one can have `DirectoryStructure = T_$(T)_Act_$(Activity)`). 
	* `CopyFrom`: path (absolute or relative to the pyrla script launching directory) to the base configuration file to be changed. This key may not contain expressions or list of values.
	* `CopyTo`: name of the base configuration whose keys will be taken from InputFrom (and modified using the InputFromOverwrite). This file will be copied to the directory given by DirectoryStructure. If this key is missing then the file will have the same name as the CopyFrom
	* `CopyToWrite`: name of the keys that should be written in the CopyTo file (if a CopyFrom is specified and it contains any of these keys they will be overwritten).
	* `CopyObjects`: one or more paths (absolute or relative to the pyrla script launching directory) to be copied under each job's working directory.
	* `Execute`: the command to execute.
	* `PreExecute`: a command to be executed before `Execute`. If the command exits with a non-zero exit code no other command will be run.
	* `PostExecute`: a command that will be executed after `Execute` if and only if `Execute` exits with a zero exit code.
	* `Relaunch`: if True relaunch jobs that return non-zero exit codes. Note that only the `Execute` command gets re-launched.
	* `ContemporaryJobs`: maximum number of jobs to be executed together. This key may not contain expressions or list of values. If 0 then no max will be set. Defaults to 0.
	* `WaitingTime`: waiting time (in seconds) between job launches. Defaults to 2 seconds.
	* `Subdirectories`: one or more directories (separated by spaces) to be created from each job under the DirectoryStructure folder. An example: `Subdirectories = confs sus/special` will create two folders under the job's working directory (determined by `DirectoryStructure``): confs and sus. In addition, a directory called "special" under the sus folder will be created.
	* `Times`: how many times the jobs must be executed.
	* `InputSeparator`: a character or a string which is used to separate keys from values in the input file (the CopyFrom one). Default is the equal sign '='.
	* `Exclusive`: if True, no more than one job per directory can be executed.
		
* The following built-in keys can be used in user-defined keys:
	* `JOB_ID`: expands to the current job's id, which is 0 for the first job, 1 for the second, etc.
	* `BASE_DIR`: the directory pyrla was launched from.
	
* It is possible to have keys take specific values when one or more conditions are met. For example, `Delta = 0.2 @@ T = 0.1, Activity = 1e-5` will assign to Delta the value 0.2 for all those processes that have the two keys T and Activity take the values 0.1 and 1e-5, respectively. As of now, the only conditions available are comma-separated lists of specific values of keys.
		
## Syntax of the CopyFrom file

pyrla supports different types of CopyFrom file. The type of file can be set by using the `InputType` key.

### Default syntax

By default pyrla expects a file containing a list of `key = value` lines. In this case

* A key listed under the `CopyToWrite` keyword will overwrite a value in the `CopyFrom` file if the `CopyFrom` file contains that same key in one of its `key = value` line. Here "same" is meant in a case sensitive way. The default separator is `=`. You can use the `InputSeparator` key in the input file to change the separator. 
* For each `CopyToWrite` key that is not in the `CopyFrom`, a `key = value` line will be appended at the end of the file.

### LAMMPS input file

If `InputFile = LAMMPS` then pyrla will expect a LAMMPS input file. In this case

* A key listed under the `CopyToWrite` keyword will overwrite a value in the `CopyFrom` file if the `CopyFrom` file contains a `variable key ...`. In this case the line will be replaced by `variable key equal value`.
* Any `CopyToWrite` key that is not in the CopyFrom file will not be used (and a warning will be issued).

### Jinja2 templates

If `InputFile = Jinja2` then pyrla will expect a [Jinja2](https://palletsprojects.com/p/jinja/) template file. In this case the values associated to the keys specified in CopyToWrite will be passed to the Jinja template. This feature requires the `jinja2` python package to be installed.
	
## Acknowledgements

* I took the idea of a python-based launcher from John Russo and his gotmilkneedpy
