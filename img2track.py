#!/usr/local/bin/python

# img2track.py
# Copyright 2012 by David "Davi" Post (DaviWorks.com)

""" Program to read graphic image file and store as pattern data formatted to
    load into a Brother KH-930 knitting machine.
"""

import sys
import os
import os.path
import logging
import traceback
import Tkinter
import tkFileDialog

import Image        # from Python Imaging Library (PIL)


version = '1.4b1'   # version number of this program


# default vertical stretch factor to compensate for stitches wider than they are tall
stretch_default = 1.5

# maximum pattern width (number of stitches)
maximum_width = 200     # KH-930 knitting bed is 200 stitches wide

initial_pattern_number = 901


class Track():
    """ Holds data for one track of external data storage.
        This data is a snapshot of the non-volatile RAM of the knitting machine."""

    def __init__(self):
        """ Initialize new track container.
            All "offsets" are measured backward from end of track data.
            Pattern storage grows backward from pattern_offset;
            program info grows forward from start of data.
        """
        # constants
        self.size = 0x800               # 2 KB
        self.pattern_offset = 0x0120    # offset to end of pattern data
        self.available_loc = 0x700      # location of offset to end of available memory
        self.pgm_info_end_loc = 0x710   # location of offset to end of program info
        self.pgm_info_size = 7          # length of one program info entry
        
        self.data = bytearray(self.size)    # (initialized to 0s)

        # store offset to end of available pattern memory
        self.set_available(self.pattern_offset)

        # store offset to end of program info
        self.set_pgm_info_end(self.size)

        # store initial pattern number in an empty program info entry
        self.add_pgm_entry(initial_pattern_number)


    def set_bytes(self, location, seq):
        """ Store seq (a sequence of bytes) in track starting at location.
            If location < 0, store at that offset from end of track."""
        self.data[location:location + len(seq)] = seq


    def available_offset(self):
        """ Offset to end of available pattern memory, measured from end of track."""
        return self.get_word(self.available_loc)

    def set_available(self, offset):
        """ Set offset to end of available memory."""
        self.set_word(self.available_loc, offset)


    def pgm_info_end(self):
        """ Offset to end of program info, measured from end of track."""
        return self.get_word(self.pgm_info_end_loc)

    def set_pgm_info_end(self, offset):
        """ Set offset to end of program info."""
        self.set_word(self.pgm_info_end_loc, offset)


    def get_word(self, loc):
        """ Return integer value of 16 bits at location loc.""" 
        return (self.data[loc] << 8) + self.data[loc + 1]

    def set_word(self, loc, word):
        """ Store 16-bit word at location loc."""
        self.data[loc:loc + 2] = two_bytes(word)


    def free_mem(self):
        """ Return number of bytes available for pattern storage."""
        return self.pgm_info_end() - self.available_offset()
    

    def pat_num(self, loc):
        """ Return pattern number of info at loc."""
        entry = self.data[loc:loc + self.pgm_info_size]
        fmt = '%02X' * self.pgm_info_size
        nibbles = fmt % tuple(entry)
        return int(nibbles[-3:])    # pattern number in last 3 nibbles of info entry
        

    def add_pgm_entry(self, pat_num):
        """ Add a new empty program info entry."""
        info = program_info(0, 0, 0, pat_num)
        offset = self.pgm_info_end()
        self.set_bytes(- offset, info)
        self.set_pgm_info_end(offset - len(info))


    def add_pattern(self, pattern, nrows, nstitches):
        """ Add pattern (bytearray) to track, and store dimensions.
            Return pattern number.
        """
        # Last program info entry always empty.
        # Assume pattern info uses sequential pattern numbers.
        if len(pattern) > self.free_mem():
            raise Error('Not enough space in track to store pattern.')

        # Find first empty program info entry
        pattern_num = initial_pattern_number
        info_end = self.size - self.pgm_info_end()
        for loc in range(0, info_end, self.pgm_info_size):
            if self.pat_num(loc) != pattern_num:
                raise BadError('Pattern numbers not sequential.')
            if self.get_word(loc) == 0:
                break       # found empty entry
            pattern_num += 1
        else:
            raise BadError('No empty entry in program info.')

        # Store pattern info entry in program info
        offset = self.available_offset()    # offset of (end of) this pattern's data
        info = program_info(offset, nrows, nstitches, pattern_num)
        self.set_bytes(loc, info)

        # Store pattern data
        offset += len(pattern)
        self.set_bytes(- offset, pattern)
        self.set_available(offset + 1)

        # Maintain empty last entry
        if loc + len(info) == info_end:
            # we filled last empty info entry, make another empty one
            self.add_pgm_entry(pattern_num + 1)
            
        return pattern_num


    def set_selector(self, selector, position, copies=0):
        """ Set selector (continuous repeat = 1, motifs = 2) and position."""
        # These settings not needed, but provide defaults (##not working yet)
        if selector not in (1, 2):
           raise Exception('Selector must be 1 or 2')
        
        # set selector and pattern number
        ##two_bytes = pack_nibbles([selector] + to_bcd(initial_pattern_number))
        two_bytes = pack_nibbles([selector] + to_bcd(0, 3))    ## no pat num for now
        self.set_bytes(0x7EA, two_bytes)

        # must also set motif 1 (for selector 2) and position
        nibbles = to_bcd(position, 3) + to_bcd(copies, 3)   # motif 1
        nibbles += to_bcd(position, 3)                      # selector 1 position
        ##self.set_bytes(0x7FB, pack_nibbles(nibbles))   # nibbles odd to align correctly
        

    def read(self, sector_path, track_num):
        """ Load track data from specified track files at sector_path."""
        sector_num = (track_num - 1) * 2
        ### Caution: track might not be stored in these sectors --
        ###     Do we need to search .id files?
        halfsize = track.size // 2
        fmt = os.path.join(sector_path, '%02d.dat')
        sector0 = read_file(fmt % sector_num)
        sector1 = read_file(fmt % sector_num + 1)
        self.set_bytes(0, sector0)
        self.set_bytes(halfsize, sector1)


    def write(self, sector_path, track_num):
        """ Write track data to specified track files at sector_path."""
        # Store track in two sector files, half in each
        sector_num = (track_num - 1) * 2
        ### We assume that this track is stored in these sectors -- OK?
        halfsize = self.size // 2
        sector0path = os.path.join(sector_path, '%02d' % sector_num)
        sector1path = os.path.join(sector_path, '%02d' % (sector_num + 1))
        write_file(sector0path + '.dat', self.data[:halfsize])
        write_file(sector1path + '.dat', self.data[halfsize:])
        # Write sector nn.id files
        sector_id = pack_nibbles(to_bcd(track_num, 2)) + bytearray(11)
        write_file(sector0path + '.id', sector_id)
        write_file(sector1path + '.id', sector_id)


class Error(Exception):
    pass

class BadError(Exception):
    """ Bad enough to report to developer."""
    pass


def program_info(offset, rows, stitches, pattern_num):
    """ Compose a program info entry (bytearray)."""
    digits = to_bcd(rows, 3) +  to_bcd(stitches, 3) + to_bcd(pattern_num, 4)
    return two_bytes(offset) + pack_nibbles(digits)


def two_bytes(num):
    """ Return 2-byte bytearray representing num."""
    if 0 <= num < (1 << 16):
        return bytearray([num >> 8, num & 0xFF])
    else:
        raise Exception('num larger than two bytes')

def to_bcd(num, width=0):
    """ Return list of nibbles for BCD representation of non-negative integer num.
        Width gives minimum number of digits. (BCD = binary coded decimal.)"""
    s = '%0*d' % (width, num)
    return [ord(digit) - ord('0') for digit in s]

def pack_nibbles(nibbles):
    """ Return bytearray containing the given sequence of nibbles.
        If length of nibbles is odd, prepend a zero nibble."""
    length = len(nibbles)
    nibbles = [0] * (length % 2) + nibbles
    return bytearray([(nibbles[i] << 4) + nibbles[i + 1] for i in range(0, length, 2)])

def print_data(data):
    fmt = '%03X:  ' + ('%02X ' * 4 + ' ') * 4       # line format = index: 16 bytes
    data = tuple(data)
    lines = [fmt % ((i,) + data[i:i + 16]) for i in range(0, len(data), 16)]
    return '\n'.join(lines)


def read_file(filepath):
    """ Return data sequence read from binary file at filepath."""
    f = open(filepath, 'rb')
    data = f.read()
    f.close()
    return data

def write_file(filepath, data):
    """ Write data sequence to binary file at filepath."""
    f = open(filepath, 'wb')
    f.write(data)
    f.close()


def encode_image(img_path, stretch, max_size, max_width):
    """ Return pattern data (as bytearray), rows, stitches for image at img_path.
        Scale image vertically by stretch factor to compensate for stitch size.
        Scale image to fit in max_size bytes.
        If wider than max_width, scale to fit."""
    img = Image.open(img_path)
    logging.info('  Image read from file "%s"' % img_path)
    logging.info('  Image size (width, height) is %s' % str(img.size))
    nstitches, nrows = img.size
    
    if stretch != 1.0:
        nrows = int(round(stretch * nrows))
        img = img.resize((nstitches, nrows), Image.ANTIALIAS)
        logging.info('  Stretched image vertically by %s to size %s' % 
                     (stretch, str(img.size)))
 
    # scale to fit in KM memory (1 track on disc)
    aspect = float(nstitches) / nrows
    max_height = ((8 * aspect * max_size + 12.25) ** 0.5 - 3.5) / aspect
    if nrows > max_height:      # too big for one track, scale to fit
        width = int(nstitches * max_height / nrows)
        if width <= max_width:
            nstitches, nrows = width, int(max_height)
            img = img.resize((nstitches, nrows), Image.ANTIALIAS)
            logging.warning('Image resized to %s to fit in one track' % str(img.size))
        # else if still too wide, will be resized appropriately by the following

    if nstitches > max_width:
        nrows = int(round(nrows * max_width / float(nstitches)))
        nstitches = max_width
        img = img.resize((nstitches, nrows), Image.ANTIALIAS)
        logging.warning('Image wider than %s, resized to %s' % (max_width, img.size))
       
    if img.mode != '1':
        img = img.convert('1')          # if not B/W, convert
    img.save(img_path + '.b+w.png')
    
    imgdata = img.getdata()
    imgbits = ''.join(['10'[pixel > 0] for pixel in imgdata])   # bit string
    # '10' above inverts the bits so dark pixels select contrast color

    # insert bits before each row to pad to a nibble boundary
    rowpadding = (- nstitches % 4) * '0'    # pad to a multiple of 4 bits
    bits = ''
    for irow in range(0, len(imgbits), nstitches):  # index to start of each row
        bits += rowpadding + imgbits[irow:irow + nstitches]
        
    bits = '0' * (- len(bits) % 8) + bits   # prepend padding to meet byte boundary
    imgbytes = [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]

    # append blank Memo data
    memo = [0] * ((nrows + 1) // 2)     # 4 bits per row, padded to byte boundary
    pattern = bytearray(imgbytes + memo)
    return pattern, nrows, nstitches


def image2track(img_path, sector_path, stretch=stretch_default, max_width=maximum_width):
    """ Read image from img_path, encode and store in specified knitting machine
        track files in folder at sector_path. Return pattern number & dimensions."""
    track = Track()
    max_pattern_size = track.free_mem() - 1
    pattern, nrows, nstitches = \
        encode_image(img_path, stretch, max_pattern_size, max_width)
    pattern_num = track.add_pattern(pattern, nrows, nstitches)
    track.set_selector(2, nstitches // 2, 1)    # selector 2, centered, 1 copy
    if debug >= 1:
        write_file(img_path + '.dat', track.data)   # save in one file with image name
    track.write(sector_path, 1)                 # write track sector files
    return pattern_num, nstitches, nrows


def logging_setup(logfilename):
    """ Set up logging: debug messages to file; info, warnings, errors to console."""
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s %(levelname)s: %(message)s',
                        filename=logfilename)
    console = logging.StreamHandler()           # console messages
    console.setLevel(logging.INFO)
    formatter = logging.Formatter('   %(levelname)s: %(message)s')
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)   # add handler to the root logger


debug = 'a' in version
logfilename = 'img2track_log.txt'

usage_message = """
    Usage: python img2track.py <image_file> <disc_folder> [ <stretch> [<max_width>] ]
    
    Brackets enclose [optional] items which may be omitted.
    
    <image_file> is the name of a file containing a graphical image.
        Most types should work: .gif, .png, .jpg, .bmp, etc.
        Darker areas will be knitted with the contrast yarn.
        Use "-i" (interactive) instead of a filename to open a file chooser dialog.
        
    <disc_folder> is the name of the folder the emulator uses to
        store disc sector files (nn.id, nn.dat).

    <stretch> is the vertical stretch factor, to adjust for stitches being
        wider than they are tall. This is optional, will default to %s if omitted.
        Use 1 for no stretch. (1.5 for 2 stitches wide = 3 rows tall)
        
    <max_width> is the maximum number of stitches wide.
        This is optional, but if included, must be preceded by <stretch>.
        Actual width may be smaller, to make the pattern fit into one track.
    """
usage_message = usage_message % stretch_default



def arg_convert(arg, default, convert_func, lo, hi, arg_name, description):
    if arg == None:
        arg = default
    else:
        try:
            arg = convert_func(arg)
            if not (lo <= arg <= hi):
                raise ValueError
        except ValueError:
            logging.error('<%s> ("%s") must be %s between %s and %s' % \
                            (arg_name, arg, description, lo, hi))
            print usage_message
            sys.exit(1)
    return arg


def ask_filename():
    root = Tkinter.Tk()
    root.withdraw()         # don't display window
    options = {'initialdir': os.getcwd(),
                'title': 'img2track %s -- Select image file' % version }
    imgpath = tkFileDialog.askopenfilename(**options)
    return imgpath
    

if __name__ == '__main__':
    logging_setup(logfilename)
    if not (3 <= len(sys.argv) <= 5):
        print usage_message
    else:
        logging.info("Running img2track version %s ..." % version)
        logging.debug(' command = ' + ' '.join(sys.argv))
        args = sys.argv + [None, None]      # at least 5 args 
        program_name, imgpath, sector_path, stretch, max_width = args[:5]
        if not os.path.isdir(sector_path):
            logging.error('<disc_folder> "%s" not found, or not a folder' % sector_path)
            sys.exit(1)
        stretch = arg_convert(stretch, stretch_default, float, 0.1, 2.0, 'stretch', 'a number')
        max_width = arg_convert(max_width, maximum_width, int, 1, 200, 'max_width', 'an integer')
        if imgpath == '-i':     # interactive
            logging.info('  Select image file in file chooser dialog window.')
            imgpath = ask_filename()
        if imgpath:
            try:
                patnum, nstitches, nrows = \
                    image2track(imgpath, sector_path, stretch, max_width)
            except (IOError, Error) as exc:
                logging.error(exc)
            except (BadError, Exception) as exc:
                report_msg = "Error in %s, please send %s to knitting@daviworks.com"
                logging.critical(report_msg % (program_name, logfilename))
                logging.critical(traceback.format_exc())
            else:
                msg = "  Stored %d x %d image in track %d as pattern number %d"
                msg = msg % (nstitches, nrows, 1, patnum)
                logging.info(msg)

