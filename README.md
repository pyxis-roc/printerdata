# printer data

Tools for gathering and storing data from a Klipper-based 3D printer.


## Installation

First, clone this repository. Then, installation into a virtual
environment is recommended.

```
python3 -m venv /path/to/venv
```

Then, enable the virtual environment:

```
source /path/to/venv/bin/activate
```

Then, in the directory containing the repository, run:

```
pip install -r requirements.txt
python setup.py install
```


## posdata.py

To capture and store position data during a print, run `posdata.py`:

```
posdata.py hostname port outputfile.csv
```

Here `hostname` is the name of the printer, `port` is usually 80, and
`outputfile.csv` will contain the position data. You can start
`posdata.py` before you start the print, it will only store position
data during an active/paused print (but not a finished/cancelled
print).  However, it is recommended to home the printer head before
starting `posdata.py`.

Each row of the output CSV file will contain three timestamps:
`rectime` which contains the time the position data was recorded,
`time` which is the time since the print started, `origts` for the
original Klipper timestamp.

## Copyright and License

Copyright (C) 2023, University of Rochester

Licensed under the GNU General Public License v3 (GPLv3) due to the
use of `[moonraker-api](https://pypi.org/project/moonraker-api/)`
