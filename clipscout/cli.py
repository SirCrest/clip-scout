"""The `scout` command. Each subcommand hands off to one module, imported only when used."""
import argparse
import sys


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    from . import __version__
    p = argparse.ArgumentParser(prog='scout', description='Clip Scout: stream in, best clips out.')
    p.add_argument('--version', action='version', version=f'Clip Scout {__version__}')
    sub = p.add_subparsers(dest='cmd', required=True)

    a = sub.add_parser('add', help='add a stream from a video file or a Twitch/YouTube URL')
    a.add_argument('source')
    a.add_argument('--title')
    a.add_argument('--date', help='YYYY-MM-DD (default: from the URL metadata or the file date)')
    a.add_argument('--mode', choices=('move', 'copy', 'link'), help='how a local file enters the library')

    a = sub.add_parser('process', help='run pending stages (agent stages open tasks and wait)')
    a.add_argument('ids', nargs='*')
    a.add_argument('--until')

    a = sub.add_parser('status', help='stage progress per stream')
    a.add_argument('ids', nargs='*')

    a = sub.add_parser('reset', help='re-run a stage and everything after it')
    a.add_argument('id')
    a.add_argument('stage')

    t = sub.add_parser('task', help='agent tasks').add_subparsers(dest='action', required=True)
    x = t.add_parser('list')
    x.add_argument('--state')
    x = t.add_parser('next', help='claim the next open task and print where its instructions are')
    x.add_argument('--type')
    x = t.add_parser('show')
    x.add_argument('id')
    x = t.add_parser('submit', help="validate the task's output.json and apply it")
    x.add_argument('id')
    x = t.add_parser('reopen')
    x.add_argument('id')

    a = sub.add_parser('work', help='have an agent CLI do open tasks in the background')
    a.add_argument('--agent', help='claude | codex | gemini | custom (default: settings.json)')
    a.add_argument('--parallel', type=int)
    a.add_argument('--type')
    a.add_argument('--limit', type=int)

    a = sub.add_parser('run', help='process every stream and work its tasks until nothing is left to do')
    a.add_argument('--agent')
    a.add_argument('--parallel', type=int)

    sub.add_parser('doctor', help='check ffmpeg, GPU, transcription model and agent CLIs')

    a = sub.add_parser('media', help='find (and with --fix, losslessly remux) fragmented source videos that open slowly')
    a.add_argument('ids', nargs='*')
    a.add_argument('--fix', action='store_true')

    a = sub.add_parser('bench', help="score the judge against staff-approved clips")
    a.add_argument('--verbose', action='store_true')

    a = sub.add_parser('edit', help='plan edits (pauses, fillers, tangents) for clips')
    a.add_argument('keys', nargs='+', help='"<stream id>/<clip id>" or a stream id for all its kept clips')

    a = sub.add_parser('render', help='render clips with their edits')
    a.add_argument('keys', nargs='+')
    a.add_argument('--lossless', action='store_true', help='stream-copy without edits')

    a = sub.add_parser('serve', help='open the app')
    a.add_argument('--port', type=int, default=8765)
    a.add_argument('--no-browser', action='store_true')

    a = sub.add_parser('publish', help='YouTube: write metadata, sign in, upload, schedule')
    a.add_argument('action', choices=('metadata', 'signin', 'channel', 'upload', 'sync', 'sheet'))
    a.add_argument('keys', nargs='*')

    args = p.parse_args(argv)
    return dispatch(args)


def dispatch(args):
    cmd = args.cmd
    if cmd == 'add':
        from .ingest import add
        s = add(args.source, title=args.title, date=args.date, mode=args.mode)
        print(s.id)
    elif cmd == 'process':
        from .pipeline import process
        process(args.ids, args.until)
    elif cmd == 'status':
        from .pipeline import status
        print(status(args.ids))
    elif cmd == 'reset':
        from . import library, pipeline
        pipeline.reset(library.get_stream(args.id), args.stage)
    elif cmd == 'task':
        from . import tasks
        return tasks.cli(args)
    elif cmd == 'work':
        from .agents import work
        work(agent=args.agent, parallel=args.parallel, kind=args.type, limit=args.limit)
    elif cmd == 'run':
        from .agents import run_all
        run_all(agent=args.agent, parallel=args.parallel)
    elif cmd == 'doctor':
        from .doctor import run
        return run()
    elif cmd == 'media':
        from . import library, media
        streams = [library.get_stream(i) for i in args.ids] if args.ids else library.all_streams()
        slow = [s for s in streams if s.media and media.is_fragmented(s.media)]
        print(f'{len(slow)} of {len(streams)} source videos are fragmented' + (':' if slow else '.'))
        if not args.fix:
            for s in slow:
                print(f'  {s.id}  {s.title[:60]}')
            return 0
        failed = []
        for attempt in range(2):  # a file another program has open can't be replaced; try those again at the end
            todo, failed = (slow, []) if attempt == 0 else (failed, [])
            for s in todo:
                print(f'  {s.id}  fixing…', flush=True)
                try:
                    r = media.fix_stream(s)
                    print(f"  {s.id}  done: {r['duration']:.0f} s, opens instantly" if r else f'  {s.id}  already fine')
                except Exception as e:
                    failed.append(s)
                    print(f'  {s.id}  skipped: {e}', flush=True)
        print(f'{len(slow) - len(failed)} fixed' + (f', {len(failed)} left: ' + ' '.join(s.id for s in failed) if failed else ''))
        return 1 if failed else 0
    elif cmd == 'bench':
        from .bench import run
        run(verbose=args.verbose)
    elif cmd == 'edit':
        from .edit import plan_keys
        plan_keys(args.keys)
    elif cmd == 'render':
        from .render import render_keys
        render_keys(args.keys, lossless=args.lossless)
    elif cmd == 'serve':
        from .server import serve
        serve(port=args.port, open_browser=not args.no_browser)
    elif cmd == 'publish':
        from .publish import cli
        return cli(args.action, args.keys)
    return 0


if __name__ == '__main__':
    sys.exit(main())
