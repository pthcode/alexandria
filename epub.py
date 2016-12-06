#!/usr/bin/env python
# -*- coding: utf8 -*-
"""
Listing epub ebook metadata and perhaps renaming the book appropriately.

This script should be called::

    python epubmetareader.py [list|rename] book1.epub book2.epub ...

Due to some variations in the way metadata is actually written, this script
does a a bit of searching and cleaning up to best extract book information. If
the "list" command is used, this metadata is dumped to the screen. If "rename"
is used, the original file is renamed in the format::

    <first author surname> (<publication year>) <short title> (isbn<isbn>).epub

This only uses the standard Python library to do its magic and should be easily
modifiable.
"""

__author__ = "Paul-Michael Agapow (pma@agapow.net)"
__version__ = '0.1'


### IMPORTS

from xml.etree import ElementTree as et
from zipfile import ZipFile
from xml.dom.minidom import parseString
import copy
import re
import types
import os

try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO

### CONSTANTS & DEFINES

OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"

DENAMESPACE_RE = re.compile (r'^.+\}')

YEAR_RE = re.compile (r'^\d\d\d\d')

CLEAN_ISBN_RE = re.compile (r'[\- ]+')


### IMPLEMENTATION ###


def rename_file (p, md):
    # tmpl = <1st author surname> (<year>) <short title> (ISBN<isbn>)
    UNKNOWN = 'UNKNOWN'

    # grab the first author or creator
    auths = md.authors() or md.creators()
    if auths:
        # extract their surname
        first_auth = auths[0]
        name = first_auth.attribs.get('file-as', '').split(',')[0] \
            or first_auth.value.split(' ')[-1] \
            or UNKNOWN

    # get year
    pubdate = None
    dateval = md.publication_date() or md.get('date')
    if dateval:
        earliest_date = sorted (dateval, cmp=lambda x, y: cmp (x.value, y.value))[0]
        m = YEAR_RE.match (earliest_date.value)
        if m:
            pubdate = m.group(0)
    if not pubdate:
        pubdate = UNKNOWN

    # get title
    short_title = None
    title = md.get('title')
    if title:
        short_title = title.value.split(':')[0]
    else:
        short_title = UNKNOWN

    # get isbn
    isbn = None
    ids = md.isbn()
    if ids:
        isbn = CLEAN_ISBN_RE.sub ('', ids[0].value).upper()
    else:
        isbn = UNKNOWN
        for x in md.identifiers():
            id_val = CLEAN_ISBN_RE.sub ('', x.value).upper()
            if len(id_val) in [10, 13]:
                isbn = id_val
                break

    # build name
    new_file_name = u"%(name)s (%(pubdate)s) %(short_title)s (isbn%(isbn)s).epub" % {
        'name': name,
        'pubdate': pubdate,
        'short_title': short_title,
        'isbn': isbn,
    }
    print(new_file_name)
    os.rename (p, new_file_name)







def pretty_print(element):
    txt = et.tostring(element)
    return parseString(txt).toprettyxml()


def strip_namespace(tag):
    """
    Remove the namespace portion of an Etree tagname.
    """
    return DENAMESPACE_RE.sub ('', tag)


def clean_attribs (attrib_dict):
    return dict ([(strip_namespace(k).lower(), v) for k,v in attrib_dict.items()])


def tag_to_metval (xml_tag):
    if xml_tag.text:
        val_name = xml_tag.text.strip()
    else:
        val_name = ''
    return MetaValue (val_name, clean_attribs(xml_tag.attrib))


class MetadataDict (dict):

    def __repr__ (self):
        return "foo"

    def __str__ (self):
        return self.__unicode__().encode ('ascii', 'replace')

    def __unicode__ (self):
        pairs = []
        for k, v in self.items():
            if type(v) == types.ListType:
                v_str = u', '.join ([a.__repr__() for a in v])
            else:
                v_str = v.__unicode__()
            pairs.append (u"'%s': '%s'" % (k, v_str))
        pair_str = u", ".join(pairs)
        return u"{%s}" % pair_str

    def creators (self, role=None):
        if role:
            return [x for x in self['creator'] if x.attribs.get('role') == role]
        else:
            return self['creator']

    def authors (self):
        return self.creators(role='aut')

    def identifiers (self, scheme=None):
        if scheme:
            return [x for x in self['identifier'] if x.attribs.get('scheme') == scheme]
        else:
            return self['identifier']

    def isbn (self):
        return self.identifiers(scheme='ISBN')

    def dates (self, event=None):
        if event:
            return [x for x in self['date'] if x.attribs.get('event') == event]
        else:
            return self['date']

    def publication_date (self):
        return self.dates (event='publication')



class MetaValue (object):
    """
    A simple representation of a metadata value.
    """
    def __init__ (self, value=None, attribs={}):
        self.value = value
        self.attribs = copy.deepcopy (attribs)

    def __str__ (self):
        return self.__unicode__().encode ('ascii', 'replace')

    def __repr__ (self):
        return "%s('%s', %s)" % (
            self.__class__.__name__,
            self.value,
            ", ".join (["%s='%s'" % (k, v) for k,v in self.attribs.items()])
        )

    def __unicode__ (self):
        return self.value


class EpubMetaReader (object):
    def __init__ (self, path):
        self.zip = ZipFile (path, mode='r')

    def get_metadata (self):
        """
        Search for and return metadata within the ebook.

        :Returns:
            A hash of the metadata tags found or `None` if nothing found.

        Note that if the metadata is found but is empty, an empty hash is returned.
        We follow this philosophy for the individual fields as well - if a field
        is not found, it doesn't appear in the metadata, but if it appears but is
        empty or cannot be parsed, an empty field appears in the metadata.

        """
        # NOTE: a contents file with malformed XML will error, which is acceptable
        # XXX: other fields to looks at
        # - subject, type
        # - date (YYYY[-MM[-DD]]: a required 4-digit year, an optional 2-digit
        # month, and if the month is given, an optional 2-digit day of month.
        # The date element has one optional OPF event attribute. The set of values
        # for event are not defined by this specification; possible values may
        # include: creation, publication, and modification.)
        # Possible roles for creastors & contributors include:
        # Artist [art]   Use for a person (e.g., a painter) who conceives, and perhaps also implements, an original graphic design or work of art, if specific codes (e.g., [egr], [etr]) are not desired. For book illustrators, prefer Illustrator [ill].
        # Author [aut]   Use for a person or corporate body chiefly responsible for the intellectual or artistic content of a work. This term may also be used when more than one person or body bears such responsibility.
        # Editor [edt]   Use for a person who prepares for publication a work not primarily his/her own, such as by elucidating text, adding introductory or other critical matter, or technically directing an editorial staff.
        # Illustrator [ill]  Use for the person who conceives, and perhaps also implements, a design or illustration, usually to accompany a written text.
        # Translator [trl]
        contents = self.read_contents_file()
        if contents:
            con_tree = et.fromstring(contents)
            metadata_tag = "{%s}metadata" % OPF_NS
            m = con_tree.find(metadata_tag)
            if m is not None:
                md_dict = MetadataDict()
                for t in ['publisher', 'language', 'title', 'description']:
                    elem = m.find("{%s}%s" % (DC_NS, t))
                    if elem != None:
                        md_dict[t] = tag_to_metval (elem)
                for t in ['creator', 'contributor', 'identifier', 'date']:
                    elems = m.findall("{%s}%s" % (DC_NS, t))
                    if elems != []:
                        md_dict[t] = [tag_to_metval (x) for x in elems]
                return md_dict
        # no file, no xml or no metadata tag
        return None

    def read_contents_file (self):
        """
        Find and return the contents of the ebook table of contents.
        """
        contents_path = self.find_contents_file()
        if contents_path:
            return self.zip.read (self.find_contents_file())
        else:
            return None

    def find_contents_file (self):
        """
        Return the path of the table of contents within the epub zip.

        :Returns:
            The location of the table of contents or `None` if it cannot be found

        While the location of the TOC is prescribed by the epub standard, in practice
        this is much violated. Therefore we looks for it in the variety of locations:

        1. The location given in the container file
        2. Within the OEBPS directory
        3. On the top level

        """
        # possible locations for the toc
        possible_paths = [
            self.contents_path_from_container(),
            'OEBPS/content.opf',
            'OEBPS/Content.opf',
            'content.opf',
            'Content.opf',
        ]
        # is there a file at any of these?
        zip_contents = self.zip.namelist()
        for p in possible_paths:
            if p in zip_contents:
                return p
        # unsucessful
        return None

    def read_container_file (self):
        """
        Return the contents of the container file.
        """
        # XXX: it *should* be here. Are there any variants?
        # TODO: need to cope with failure?
        return self.zip.read ('META-INF/container.xml')

    def contents_path_from_container (self):
        """
        Return the location of the TOC file as given in the container file.

        :Returns:
            A path within the zip, or `None` if not found.

        """
        # TODO: can we cope with namespace variants (but synonyms)?
        # XXX: are there any actual variants?
        container_text = self.read_container_file()
        if container_text:
            container_tree = et.fromstring(container_text)
            ns = "urn:oasis:names:tc:opendocument:xmlns:container"
            rootfile = container_tree.find("{%s}rootfiles/{%s}rootfile" % (ns, ns))
            if rootfile != None:
                return rootfile.attrib.get("full-path", None)
        return None



class PdfMetaReader (object):
    def __init__ (self, path):
        from pyPdf import PdfFileReader
        self.doc = PdfFileReader(open(p, 'rb'))

    def get_metadata (self):
        return self.rdr.documentInfo, self.rdr.xmpMetadata


### MAIN ###

def parse_args():
    # Construct the option parser.
    usage = '%prog COMMAND [OPTIONS] INFILE [INFILE ...]'
    version = "version %s" %  __version__
    #epilog='Input and output format is currenlty limited to FASTA.'

    optparser = OptionParser (usage=usage, version=version, epilog=epilog)

    #optparser.add_option ('-d', '--date-format',
    #   dest="date_format",
    #   action='store',
    #   default="plain",
    #   metavar='FMT',
    #   help="Set the format for parsing the date.",
    #)

    options, pargs = optparser.parse_args()
    if (len(pargs) != 2):
        optparser.error ('Need at least two arguments (command and input files)')
    cmd, infiles = pargs[0].lower(), pargs[1:]
    assert (cmd in ['info', 'list', 'rename']), "unrecognised command '%s'" % cmd

    return cmd, infiles, options


def main():
    cmd, infiles, options = parse_args()

    for p in in_files:
        print("* Reading '%s' ..." % p)
        rdr = EpubMetaReader (p)
        md = rdr.get_metadata()

        if op in ['info', 'list']:
            # dump metadata to screen
            buf = StringIO()
            buf.write (u"----\n" % p)
            buf.write (u"- path: %s\n" % p)
            for k, v in md.items():
                buf.write (u"- %s:" % k)
                if type(v) == types.ListType:
                    buf.write (u"\n")
                    for x in v:
                        buf.write (u"\t- %s" % x)
                        att_str = ', '.join(["%s: '%s'" % (a, b) for a, b in x.attribs.items()])
                        if att_str:
                            buf.write (u" (%s)\n" % att_str)
                        else:
                            buf.write (u"\n")
                else:
                    buf.write (u" %s" % v)
                    x = v
                    att_str = ', '.join(["%s='%s'" % (a, b) for a, b in x.attribs.items()])
                    if att_str:
                        buf.write (u" (%s)\n" % att_str)
                    else:
                        buf.write (u"\n")
            buf.write (u"\n")
            print (buf.getvalue().encode ('ascii', 'replace'))
        elif op in ['raw']:
            print(str(md))
        elif op in ['rename']:
            rename_file (p, md)




if __name__ == '__main__':
    main()


### END #######################################################################
