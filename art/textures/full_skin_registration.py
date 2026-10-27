"""Check native source chart registration before generating companion maps."""
import argparse
import hashlib
import json
from pathlib import Path

from record_paths import portable_record, resolve_record
import numpy as np

from full_skin_compose import (_chart_mask, _chart_registration, _match_charts, _path,
                               _read_image, _registration_metrics, source_charts)


def check_sources(manifest_path, output_dir=None):
    """Return every ready base's verdict; missing bases remain pending."""
    path = Path(manifest_path)
    manifest = resolve_record(json.loads(path.read_text()))
    if manifest.get('source_atlas_manifest'):
        source = _path(manifest['source_atlas_manifest'], path.parent)
        return check_sources(source, output_dir or path.parent / 'registration_diagnostics')
    groups = manifest['groups']
    report = {}
    for name, group in groups.items():
        source = _path(group['source_path'], path.parent)
        if not source.exists():
            report[name] = {'status': 'pending'}
            continue
        try:
            image = _read_image(source, True)
            charts = sorted(group['charts'], key=lambda c: (c['guide_box'][1], c['guide_box'][0]))
            labels, candidates = source_charts(image, len(charts), group.get('source_stitch'))
            mask = _read_image(_path(group['mask'], path.parent)) > 0
            candidates = _match_charts(name, charts, labels, candidates, mask, path.parent,
                                       manifest.get('guide_size', 1536))
            registrations = []
            errors = []
            covered = np.zeros_like(mask)
            for chart, (source_id, box, _) in zip(charts, candidates):
                selected = _chart_mask(name, chart, mask, path.parent)
                evidence = _registration_metrics(chart, source_id, box, labels, selected)
                try:
                    _chart_registration(name, chart, source_id, box, labels, mask, path.parent)
                    evidence['status'] = 'passed'
                except ValueError as error:
                    evidence.update(status='failed', error=str(error))
                    errors.append(str(error))
                x0, y0, x1, y1 = chart['atlas_box']
                if np.any(covered[y0:y1, x0:x1] & selected):
                    errors.append(f'{name}: chart masks overlap')
                covered[y0:y1, x0:x1] |= selected
                registrations.append(evidence)
            if not np.array_equal(covered, mask):
                errors.append(f'{name}: chart masks leave {int((mask & ~covered).sum())} group texels uncovered')
            report[name] = {'status': 'failed' if errors else 'passed', 'charts': registrations,
                            'source_path': str(source), 'native_size': list(image.shape[1::-1]),
                            'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
            if errors:
                report[name]['error'] = '; '.join(errors)
        except (ValueError, OSError) as error:
            report[name] = {'status': 'failed', 'source_path': str(source), 'error': str(error)}
    output = Path(output_dir) if output_dir is not None else path.parent / 'registration_diagnostics'
    output.mkdir(parents=True, exist_ok=True)
    (output / 'source_registration.json').write_text(json.dumps(portable_record(report), indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    from texture_sources import require_texture_sources
    require_texture_sources()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=Path(__file__).resolve().parents[2] /
                        '.cache/review/wave2/p9b-round2/full/parts.json')
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    report = check_sources(args.manifest, args.output_dir)
    print(json.dumps(portable_record({name: item['status'] if item['status'] != 'failed' else item['error']
                      for name, item in report.items()})))
    raise SystemExit(1 if any(item['status'] == 'failed' for item in report.values()) else 0)
