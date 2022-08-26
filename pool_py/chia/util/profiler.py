# decompyle3 version 3.9.0
# Python bytecode version base 3.7.0 (3394)
# Decompiled from: Python 3.7.9 (tags/v3.7.9:13c94747c7, Aug 17 2020, 18:58:18) [MSC v.1900 64 bit (AMD64)]
# Embedded file name: chia\util\profiler.py
import asyncio, cProfile, logging, pathlib
from chia.util.path import mkdir, path_from_root

async def profile_task(root_path: pathlib.Path, service: str, log: logging.Logger) -> None:
    profile_dir = path_from_root(root_path, f"profile-{service}")
    log.info('Starting profiler. saving to %s' % profile_dir)
    mkdir(profile_dir)
    counter = 0
    while True:
        pr = cProfile.Profile()
        pr.enable()
        await asyncio.sleep(1)
        pr.create_stats()
        pr.dump_stats(profile_dir / ('slot-%05d.profile' % counter))
        log.debug('saving profile %05d' % counter)
        counter += 1


if __name__ == '__main__':
    import sys, pstats, io
    from colorama import init, Fore, Back, Style
    from subprocess import check_call
    profile_dir = pathlib.Path(sys.argv[1])
    init(strip=False)

    def analyze_cpu_usage(profile_dir: pathlib.Path):
        counter = 0
        try:
            while True:
                f = io.StringIO()
                st = pstats.Stats((str(profile_dir / ('slot-%05d.profile' % counter))), stream=f)
                st.strip_dirs()
                st.sort_stats(pstats.SortKey.CUMULATIVE)
                st.print_stats()
                f.seek(0)
                total = 0.0
                sleep = 0.0
                for line in f:
                    if ' function calls ' in line:
                        if ' in ' in line:
                            if not total == 0:
                                raise AssertionError
                            else:
                                total = float(line.split()[-2])
                            continue
                    columns = line.split(None, 5)
                    if not len(columns) < 6:
                        if columns[0] == 'ncalls':
                            continue
                        if "{method 'poll' of 'select.epoll' objects}" in columns[5]:
                            sleep += float(columns[3])

                if sleep < 1e-06:
                    percent = 100.0
                else:
                    percent = 100.0 * (total - sleep) / total
                if percent > 90:
                    color = Fore.RED + Style.BRIGHT
                else:
                    if percent > 80:
                        color = Fore.MAGENTA + Style.BRIGHT
                    else:
                        if percent > 70:
                            color = Fore.YELLOW + Style.BRIGHT
                        else:
                            if percent > 60:
                                color = Style.BRIGHT
                            else:
                                if percent < 10:
                                    color = Fore.GREEN
                                else:
                                    color = ''
                quantized = int(percent // 2)
                print(('%05d: ' + color + '%3.0f%% CPU ' + Back.WHITE + '%s' + Style.RESET_ALL + '%s|') % (
                 counter, percent, ' ' * quantized, ' ' * (50 - quantized)))
                counter += 1

        except Exception as e:
            try:
                print(e)
            finally:
                e = None
                del e


    def analyze_slot_range(profile_dir: pathlib.Path, first: int, last: int):
        if last < first:
            print('ERROR: first must be <= last when specifying slot range')
            return
        files = []
        for i in range(first, last + 1):
            files.append(str(profile_dir / ('slot-%05d.profile' % i)))

        output_file = 'chia-hotspot-%d' % first
        if first < last:
            output_file += '-%d' % last
        print('generating call tree for slot(s) [%d, %d]' % (first, last))
        check_call(['gprof2dot', '-f', 'pstats', '-o', output_file + '.dot'] + files)
        with open(output_file + '.png', 'w+') as f:
            check_call(['dot', '-T', 'png', output_file + '.dot'], stdout=f)
        print('output written to: %s.png' % output_file)


    if len(sys.argv) == 2:
        analyze_cpu_usage(profile_dir)
    else:
        if len(sys.argv) in (3, 4):
            first = int(sys.argv[2])
            last = int(sys.argv[3]) if len(sys.argv) == 4 else first
            analyze_slot_range(profile_dir, first, last)
        else:
            print('USAGE:\nprofiler.py <profile-directory>\n    Analyze CPU usage at each 1 second interval from the profiles in the specified\n    directory. Print colored timeline to stdout\nprofiler.py <profile-directory> <slot>\nprofiler.py <profile-directory> <first-slot> <last-slot>\n    Analyze a single slot, or a range of time slots, from the profile directory\n')