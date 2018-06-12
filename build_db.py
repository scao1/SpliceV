#!/usr/bin/env python
import sys
from collections import defaultdict
import sqlite3
import os
import argparse
 

def parse_args():

    '''The only requirement is a gtf file. Provide an unstranded (or two stranded) wig file for coverage,
    a splice junction bed file for canonical splice junctions, and a backsplice junction bed file for circles.
    An output path is optional - if omitted, the db will be saved in the working directory.'''
    
    parser = argparse.ArgumentParser(description='Build database for use with "plot_transcript" script.', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("-g", "--gtf", required=True, dest='gtf_path', type=str, help="GTF path", metavar='')
    parser.add_argument("-wn", "--wigneg", dest='negwig', type=str, help="Negative strand wig path", metavar='')
    parser.add_argument("-wp", "--wigpos", dest='poswig', type=str, help='Positive strand wig path', metavar='')
    parser.add_argument("-w", "--wig", dest='wig', type=str, help='Unstranded wig path (Overrides "-wp" and "-wn")', metavar='')
    parser.add_argument("-sj", "--splicejunction", dest='sjbed', type=str, help='Canonical splice junction tab delimited bed file path. Order must be Chromosome, Start, Stop, Strand, Counts', metavar='') 
    parser.add_argument("-c", "--circlejunction", dest='circbed', type=str, help='Backsplice junction tab delimited bed file path. Order must be Chromosome, Start, Stop, Strand, Counts', metavar='')
    parser.add_argument("-o", "--output", type=str, dest='out', help='Output directory', metavar='')
    args = parser.parse_args()

    return args


def store(gtf_path, max_coord, interval):

    ''' Build a dictionary indexed by interval, with transcript info stored according to chromosomal coordinates.
    
    i.e. {
        chr1: {
            0: {
                'ENST000112341__1': (500, 1200, -, [], EGFR),
                }
            10000: {
                'ENST000351001__1': (10220, 14000, +, [], COL1A1)
            }
        },
        

    }

    Each key points to a tuple containing start, stop, strand, an empty list (to append coverage to while parsing wig file), and the gene name.    '''
    
    print("Loading gtf file..")
    line_num = 0

    master = {}
    with open(gtf_path) as gtf:
        for line in gtf:
            line_num += 1
            if line_num % 100000 == 0:
                print("%i lines processed" % line_num)

            if line[0] != '#':
                line = line.split('\t')
                chromosome = line[0]
            
                if line[2] != 'exon':
                    continue
            
                if chromosome not in master:
                    master[chromosome] = {i: {} for i in range(0, max_coord, interval)}             
            
                start = int(line[3])
                stop = int(line[4])
                strand = line[6]
            
                try:
                    gene = line[-1].split('gene_name')[1].split('"')[1]
                except IndexError:
                    gene = line[-1].split('gene_id')[1].split('"')[1]
            
                transcript = line[-1].split('transcript_id')[1].split('"')[1]
                exon = line[-1].split('exon_number ')[1].split(';')[0].replace('"','')
                exon_id = '__'.join([transcript, exon])
                entry = interval * (start // interval)
                master[chromosome][entry][exon_id]=(start, stop, strand, [], gene)

    return master


def build_coverage_dict(master, wigpath, strand=False):

    print("Storing coverage data from %s" % wigpath)
    line_num = 0
    with open(wigpath, "r") as wigfile:
        for line in wigfile:
            line_num += 1
            if line_num % 10000000 == 0:
                print("%i lines processed")

            # Wig file lines beginning with "variable step=chrN" mark beginning of that chromosome 
            if line[0] == 'v':
                chromosome = line.strip('\n').split('=')[1]
                print("Chromosome:", chromosome) 

            else:            
                line_split = line.split("\t")   
                position = int(line_split[0])   
                coverage = float(line_split[1]) 
                primary = interval * (position // interval)  

                try:
                    if strand:         
                        for key, value in master[chromosome][primary].items():                      
                            if value[1] >= position >= value[0] and value[2] == strand:  
                                master[chromosome][primary][key][3].append(coverage) 
                    else:
                        for key, value in master[chromosome][primary].items():                    
                            if value[1] >= position >= value[0]:
                                master[chromosome][primary][key][3].append(coverage) 

                except KeyError:                      
                    print("Make sure chromosome labels are consistent between all input files. Coverage information for chromosome: %s",
                            "will not be considered")


def build_sample_db(parsed_args):
  
    master = store(gtf_path, max_coord, interval)

    if parsed_args.wig:
        build_coverage_dict(master, parsed_args.wig)

    elif parsed_args.negwig and parsed_args.poswig: 
        build_coverage_dict(master, parsed_args.negwig, strand='-')
        build_coverage_dict(master, parsed_args.poswig, strand='+')

    table_name = 'coverage' 
    conn = sqlite3.connect('%s.db' % out)
    c = conn.cursor()
    c.execute("CREATE TABLE %s ( gene text, transcript text, exon int, coverage real, chromosome text, start int, stop int, strand text)" % table_name)
    
    for chromosome in master:
        for position in master[chromosome]:
            for exon_id, values in master[chromosome][position].items():
                transcript, exon = exon_id.split('__')
                start, stop, strand, base_coverage, gene = values
                coverage = sum(base_coverage) / (1 + stop - start) 
                c.execute("INSERT INTO %s VALUES(?,?,?,?,?,?,?,?)" % table_name, (gene, transcript, exon, coverage, chromosome, start, stop, strand))
    
    conn.commit()
    conn.close()


def build_junction_table(bed_path, table_name):

    print("Building junction table %s" % table_name)
    conn = sqlite3.connect('%s.db' % out)
    c = conn.cursor()
    c.execute("CREATE TABLE %s ( chromosome text, start int, stop int, strand text, counts int)" % table_name)

    with open(bed_path, "r") as input_file:
        for line in input_file:
            chromosome, start, stop, strand, counts, *_= line.strip().split()
            start = int(start) + 1  # Bed format is 0 indexed
            stop = int(stop) + 1
            c.execute("INSERT INTO %s VALUES(?,?,?,?,?)" % table_name, (chromosome, start, stop, strand, counts))

    conn.commit()
    conn.close()


args = parse_args()
gtf_path = args.gtf_path
out = args.out

try:
    conn = sqlite3.connect('%s.db' % out)
except sqlite3.OperationalError:
    sys.exit("%s.db cannot be opened." % out)

conn.close()

max_coord = 400000000   # If there is a chromosome larger than this, increase this number
interval = 10000  
#for handle in args:
 #   if not os.path.exists(handle):
  #      sys.exit(("{} was not found".format(handle)))

build_sample_db(parsed_args=args)
build_junction_table(bed_path=args.sjbed, table_name="canonical")
build_junction_table(bed_path=args.circbed, table_name="circle")
