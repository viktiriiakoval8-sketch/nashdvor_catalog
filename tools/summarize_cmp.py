"""Summarize completed CMP evaluations without counting repeated photos twice."""
import argparse
import json
from pathlib import Path
from statistics import median


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('reports',type=Path,nargs='+')
    args=parser.parse_args()
    unique={}
    for path in args.reports:
        report=json.loads(path.read_text(encoding='utf-8'))
        for row in report['images']:
            unique[row['id']]=dict(row,report=str(path.resolve()))
    rows=list(unique.values())
    reference=sum(r['referencePixels'] for r in rows)
    excluded=sum(r['excludedPixels'] for r in rows)
    intersection=sum(r['intersectionPixels'] for r in rows)
    accepted=[r for r in rows if r['accepted']]
    summary=dict(uniquePhotos=len(rows),automaticallyAccepted=len(accepted),
        pixelRecall=intersection/max(1,reference),pixelPrecision=intersection/max(1,excluded),
        medianSeconds=median(r['seconds'] for r in rows) if rows else None,
        acceptedWithOver10PercentOpeningPainted=sum(
            r['paintedOpeningPixels']/max(1,r['referencePixels'])>.1 for r in accepted),
        purpose='Development diagnostics only; no training; annotated windows and doors only. Mixed configuration runs must not be treated as a controlled comparison.',
        reports=[str(p.resolve()) for p in args.reports],images=rows)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Проверка CMP Facade Database','',
        f"Уникальных фото: {len(rows)}. Приняты автоматической геометрией: {len(accepted)}.",
        f"Доля найденных пикселей размеченных окон/дверей: {summary['pixelRecall']:.1%}.",
        f"Доля пикселей окон/дверей среди исключённых: {summary['pixelPrecision']:.1%}.",
        f"Принятых результатов с ошибочной облицовкой более 10% размеченных проёмов: {summary['acceptedWithOver10PercentOpeningPainted']}.",
        '', 'Это диагностика на выпрямленных фасадах, а не оценка качества на фото частных домов. '+
        'Принятие по геометрии не означает правильное распознавание. Исключения могут включать рамы и подоконники, не размеченные как окно. '+
        'Обучение не выполнялось. Повторные фото учитываются по последнему переданному отчёту.', '',
        'Источник: [CMP Facade Database](https://cmp.felk.cvut.cz/~tylecr1/facade/), '+
        'Radim Tylecek, Radim Sara, GCPR 2013. Лицензия издателя: CC BY-SA.', '',
        '| Фото | Найдено пикселей проёмов | Лишние исключения* | Закрашено проёмов | Геометрия принята |',
        '|---|---:|---:|---:|---|']
    for r in sorted(rows,key=lambda row:row['id']):
        lines.append(f"| {r['id']} | {r['openingRecall']:.1%} | {1-r['openingPrecision']:.1%} | {r['paintedOpeningPixels']/max(1,r['referencePixels']):.1%} | {'да' if r['accepted'] else 'нет'} |")
    lines+=['','*Относительно классов window/door: рамки, декор и другие законные исключения тоже могут попадать в эту долю.']
    args.output.with_suffix('.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k not in {'images','reports'}},ensure_ascii=False))


if __name__=='__main__':
    main()
