#!/usr/bin/env python
from Bio.Seq import Seq
from Bio import SeqIO
from Bio.SeqRecord import SeqRecord

import cProfile

import os
import sys
import argparse

import re
import numpy as np

from joblib import Parallel, delayed
import edlib


ED_THRESHOLD = 0.5

def cnt_edist(lst):
    if len(str(lst[0])) == 0:
        return -1
    if len(str(lst[1])) == 0:
        return -1
    ed_er = int(ED_THRESHOLD*len(lst[0]))
    result = edlib.align(str(lst[0]), str(lst[1]), mode="NW", task="locations", k = ed_er)
    if result["editDistance"] == -1:
        return -1
    return 100 - result["editDistance"]*100//max(len(lst[0]), len(lst[1]))

def cnt_infix_edist(lst):
    if len(str(lst[0])) == 0:
        return -1
    if len(str(lst[1])) == 0:
        return -1
    ed_er = int(ED_THRESHOLD*len(lst[0]))
    result = edlib.align(str(lst[0]), str(lst[1]), mode="HW", task="locations", k = ed_er)
    if result["editDistance"] == -1:
        return -1, None
    return 100 - result["editDistance"]*100//len(lst[0]), result["locations"][0]

def cnt_suffix_edist(lst):
    if len(str(lst[0])) == 0:
        return -1, -1
    if len(str(lst[1])) == 0:
        return -1, -1
    ed_er = int(ED_THRESHOLD*len(lst[0]))
    result = edlib.align(str(lst[0])[::-1], str(lst[1])[::-1], mode="SHW", task="locations", k = ed_er)
    if result["editDistance"] == -1:
        return -1, -1 
    return 100 - result["editDistance"]*100//len(lst[0]), len(lst[1]) - result["locations"][0][1] - 1

def load_fasta(filename, tp = "list"):
    if tp == "map":
        records = SeqIO.to_dict(SeqIO.parse(filename, "fasta"))
    else:
        records = list(SeqIO.parse(filename, "fasta"))
    return records

def make_record(seq, name, sid, d=""):
    return SeqRecord(seq, id=sid, name=name, description = d)

def add_rc_monomers(monomers):
    res = []
    for m in monomers:
        res.append(m)
        res.append(make_record(m.seq.reverse_complement(), m.name + "'", m.id + "'"))
    return res

def perform_fitting_alignment(read, monomers):
    fitting_alignment = {}

    for m in monomers:
        fitting_alignment[m.name] = []
        for i in range(len(read)):
            identity, start = cnt_suffix_edist([m.seq, read[: i + 1]])
            fitting_alignment[m.name].append([identity, start])

    return fitting_alignment

def build_hashtables(monomers, r_len):
    res = {}
    p = 31
    mm = 10**9 + 9
    m_len = 200
    k = 5
    mp = {"A": 1, "C": 2, "G": 3, "T":4}
    powers = [0 for _ in range(r_len)]
    powers[0] = 1
    for i in range(1, r_len):
        powers[i] = (powers[i-1]*p) % mm
    for m in monomers:
        hashes = {}
        h = [0 for _ in range(len(m.seq) + 1)]
        for i in range(len(m.seq)):     
            h[i + 1] = (h[i] + mp[m.seq[i]] * powers[i]) % mm

        for i in range(len(m.seq) - k):
            cur_h = (h[i + k] + mm - h[i])
            cur_h = (cur_h * powers[r_len - i - 1]) % mm
            if not cur_h in hashes:
                hashes[cur_h] = 0
            hashes[cur_h] += 1
        res[m.name] = hashes
        # print(m.name)
        # print(hashes)

    # for m in monomers:
    #     if not m.name.endswith("'"):
    #         ans = []
    #         for mm in monomers:
    #             if not mm.name.endswith("'"):
    #                 set_m = set(res[m.name].keys())
    #                 set_mm = set(res[mm.name].keys())
    #                 ans.append(str(len(set_m & set_mm)))
    #                 #print([m.name, mm.name, len(set_m), len(set_mm), len(set_m & set_mm)])
    #         print("\t".join(ans))
    # exit(-1)
    return res

def perform_hash_alignment(read, monomers):
    r_len = len(read.seq)
    monomers_hashtable = build_hashtables(monomers, r_len)

    p = 31
    mm = 10**9 + 9
    mp = {"A": 1, "C": 2, "G": 3, "T":4}
    powers = [0 for _ in range(r_len)]
    powers[0] = 1
    for i in range(1, r_len):
        powers[i] = (powers[i-1]*p) % mm

    hashes = {}
    h = [0 for _ in range(r_len + 1)]
    for i in range(r_len):
        h[i + 1] = (h[i] + mp[read.seq[i]] * powers[i]) % mm

    m_len = 170
    k = 5
    res = [0 for _ in range(len(read.seq))]

    fitting_alignment = {}
    for m in monomers:
        fitting_alignment[m.name] = [0 for _ in range(r_len)]

    for m in monomers:
        common_hashes = [0 for _ in range(r_len)]
        for i in range(r_len - k):
            cur_h = (h[i + k] + mm - h[i])
            cur_h = (cur_h * powers[r_len - i - 1]) % mm
            common_hashes[i + k] = common_hashes[i + k - 1]
            if cur_h in monomers_hashtable[m.name]:
                common_hashes[i + k] += 1
        for i in range(m_len - k, r_len - k):
            fitting_alignment[m.name][i + k] = common_hashes[i + k] - common_hashes[i + k - m_len]

    return fitting_alignment


def choose_best(read, read_dp, i, monomers, identity_dif):
    best_score, best_ind, best_monomer = -1, -1, ""
    identities = []
    for m in monomers:
        identity, start = cnt_suffix_edist([m.seq, read[: i + 1]])
        prev = 0
        if start - 1 >= 0:
            prev = read_dp[start-1]
        if identity > 70:
            if identity + prev > best_score:
                best_score, best_ind, best_monomer = identity + prev, start, m.name
    if best_score > -1:
        best_idnt = best_score 
        if best_score - read_dp[best_ind - 1] >= 0:
            best_idnt -= read_dp[best_ind - 1]
        for m in monomers:
            idnt = cnt_edist([m.seq, read[best_ind: i + 1] ])
            if idnt + identity_dif >= best_idnt and best_idnt != -1:
                identities.append([m.name, idnt])
        identities = sorted(identities, key = lambda x: -x[1])
    return best_score, best_ind, best_monomer, identities


def choose_best_hash(read, read_dp, i, monomers, identity_dif, hash_alignment_res):
    best_score, best_ind, best_monomer = -1, -1, ""
    identities = []
    for m in monomers:
        identity = hash_alignment_res[m.name][i]
        prev = 0 
        if i - 170 - 1 >= 0:
            prev = read_dp[i - 170 -1]
        if identity > 50:
            if identity + prev > best_score:
                best_score, best_ind, best_monomer = identity + prev, i - 170, m.name
    if best_score > -1:
        best_idnt = best_score - read_dp[best_ind - 1]
        for m in monomers:
            idnt = hash_alignment_res[m.name][i] #cnt_edist([m.seq, read[best_ind: i + 1] ])
            if idnt + identity_dif >= best_idnt:
                identities.append([m.name, idnt])
        identities = sorted(identities, key = lambda x: -x[1])

    return best_score, best_ind, best_monomer, identities

def slow_edlib_version(args):
    r, monomers, identity_dif = args[0], args[1], args[2]
    perform_hash_alignment(r, monomers)
    hash_alignment_res = perform_hash_alignment(r, monomers) #perform_fitting_alignment(r, monomers)
    read_len = len(r.seq)
    read_dp = [0 for _ in range(read_len)]
    ans_dp = [0 for _ in range(read_len)]
    monomer_dp = ["" for _ in range(read_len)]
    identity_dp = [[] for _ in range(read_len)]
    ans_dp[0] = -1
    for i in range(1, read_len):
        read_dp[i], ans_dp[i], monomer_dp[i], identity_dp[i] = choose_best_hash(r.seq, read_dp, i, monomers, identity_dif, hash_alignment_res)
        if read_dp[i] < read_dp[i - 1]:
            read_dp[i], ans_dp[i], monomer_dp[i], identity_dp[i] = read_dp[i-1], i - 1, "", []
    ans = []
    ind = read_len - 1
    while ind >= 0:
        if monomer_dp[ind] == "" and len(ans) > 0 and ans[-1][2] == "":
            ans[-1] = ans_dp[ind], ans[-1][1], "", ""
        else:
            ans.append([ans_dp[ind], ind, monomer_dp[ind], identity_dp[ind]])
        ind = ans_dp[ind]

    return [r.name, ans[::-1]]

def transform_to_map(args):
    alns, name = args
    res = []
    for m in alns[1]:
        if m[0] != -1 and m[2] != "":
            ind = int(alns[0])
            cur_name = m[2]
            start, end = ind + m[0], ind + m[1]
            if len(m[3]) == 0:
                exit(-1)
            for aa in m[3]:
                if aa[0] == cur_name:
                    idnt = aa[1]
                    break
            res.append([name, ind, m[2], m[0], m[1], m[3], idnt, "+"])
    return res

def realign(args):
    read, monomers, alns = args
    sorted_alns = sorted(alns, key = lambda x: -x[6])
    colored = [[i,i] for i in range(len(read))]
    new_alns = []
    m_map = {}
    for i in range(len(monomers)):
        m_map[monomers[i].name] = i
    for a in sorted_alns:
        start, end = colored[max(a[3] - 10, 0)][1], colored[min(a[4] + 10, len(read) - 1)][0]
        aln, locations = cnt_infix_edist([monomers[m_map[a[2]]].seq, read.seq[start: end + 1]])
        if aln > 70:
            new_start, new_end = start + locations[0], start + locations[1]
            start, end = new_start, new_end
            new_alns.append([a[0], a[1], a[2], start, end, a[5], aln, "+"])
            for j in range(start, end + 1):
                if j - 1 < 0:
                    colored[j][0] = -1
                else:    
                    colored[j][0] = colored[j - 1][0]
            for j in range(end, start - 1, -1):
                if j + 1 >= len(read):
                    colored[j][1] = -1
                else:
                    colored[j][1] = colored[j + 1][1]
    sorted_alns = sorted(new_alns, key = lambda x: x[3])
    return sorted_alns



def transform_alignments(alns, new_reads, s):
    res = []
    prev = {"name": None, "start": None, "end": None, "idnt": None}
    for i in range(len(alns)):
        a = alns[i]
        for m in a:
            name, ind, cur_name, start_local, end_local, lst, idnt = m[:-1]
            start, end = ind + start_local, ind + end_local
            if cur_name == prev["name"] and end - prev["end"] < 150:
                if idnt > prev["idnt"]:
                    res[-1] = [name, ind, cur_name, start_local, end_local, lst, idnt, "+"]
            else:
                res.append([name, ind, cur_name, start_local, end_local, lst, idnt, "+"])
            prev = {"name": cur_name, "start": start, "end": end, "idnt": idnt}
    WINDOW = 5
    idnts = []
    l = 0
    for it in res:
        idnts.append(it[6])
        sm = sum(idnts[l:])/(len(idnts) - l)
        if sm < 80:
            it[7] = "?"
        if len(idnts) > WINDOW:
            l += 1
    return res        


def parallel_edlib_version(reads, monomers, outfile, t, identity_dif):
    LEN_STEP = 5000
    THREADS = int(t)
    SAVE_STEP = 300
    save_step = []
    new_reads = []
    for r in reads:
        cnt = 0
        for i in range(0, len(r.seq), LEN_STEP):
            if len(r.seq) - i >= 200:
                new_reads.append(make_record(r.seq[i: min(i + LEN_STEP + 200, len(r.seq))], str(i), str(i), r.name))
                cnt += 1
        save_step.append(cnt)
    print("Initial number of reads: " + str(len(reads)) + ", Divided into chunks and reverse complement: " + str(len(new_reads)))
    with open(outfile, "w") as fout:
        fout.write("")
    
    start = 0
    for j in range(0, len(save_step)):
        all_ans = Parallel(n_jobs=THREADS)(delayed(slow_edlib_version)([new_reads[i], monomers, identity_dif]) for i in range(start, min(start + save_step[j], len(new_reads)) ))
        all_ans = Parallel(n_jobs=THREADS)(delayed(transform_to_map)([all_ans[i - start], new_reads[i].description]) for i in range(start, min(start + save_step[j], len(new_reads)) ))
        all_ans = Parallel(n_jobs=THREADS)(delayed(realign)([new_reads[i], monomers, all_ans[i - start]]) for i in range(start, min(start + save_step[j], len(new_reads)) ))
        all_ans = transform_alignments(all_ans, new_reads, start)
        print("Read " + new_reads[start].description + " aligned")
        with open(outfile[:-len(".tsv")] + "_alt.tsv", "a+") as fout_alt:
            with open(outfile, "a+") as fout:
                for a in all_ans:
                    name = a[0]
                    ind = a[1]
                    fout.write("\t".join([name, str(a[2]), str(ind + a[3]), str(ind + a[4]), "{:.2f}".format(a[6]), a[7]]) + "\n")
                    add_star = True if len(a[5]) > 1 else False 
                    for alt in a[5]:
                        if add_star:
                            fout_alt.write("\t".join([name, str(alt[0]), str(ind + a[3]), str(ind + a[4]), "{:.2f}".format(alt[1]), "*"]) + "\n")
                        else:
                            fout_alt.write("\t".join([name, str(alt[0]), str(ind + a[3]), str(ind + a[4]), "{:.2f}".format(alt[1])]) + "\n")
        start += save_step[j]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Find highest score decomposition of each read into monomers')
    parser.add_argument('-s', '--sequences', help='fasta-file with long reads sequences', required=True)
    parser.add_argument('-m', '--monomers', help='fasta-file with monomers', required=True)
    parser.add_argument('-o', '--out',  help='output tsv-file, by default will be saved into decomposition.tsv', required=False)
    parser.add_argument('-i', '--identity', help='difference in identity for printed alignments, default i = 10', required=False)
    parser.add_argument('-t', '--threads', help='threads number', required=False)

    args = parser.parse_args()
    t = args.threads
    if t == None:
        t = "1"
    i = args.identity
    if i == None:
        i = 10
    else:
        i = int(i)
    print("Number of threads: " + t)
    outfile = args.out
    if outfile == None:
        outfile = "./decomposition.tsv"

    reads = load_fasta(args.sequences)
    monomers = load_fasta(args.monomers)

    monomers = add_rc_monomers(monomers)

    #cProfile.run("parallel_edlib_version(reads, monomers, outfile, t, i)")
    parallel_edlib_version(reads, monomers, outfile, t, i)
