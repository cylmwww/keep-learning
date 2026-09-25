() => {
    const update = () => {
        const root = document.getElementById('le-course-stage-base');
        const source = document.querySelector('#le-chapter-metadata [data-chapters]');
        if (!root) return;
        let chapters = {};
        try { chapters = JSON.parse(source?.dataset.chapters || '{}'); } catch { return; }
        let previousUnit = null;
        let previousLecture = null;
        const wanted = new Set();
        for (const input of root.querySelectorAll('input[type="radio"]')) {
            const label = input.closest('label');
            const info = chapters[input.value];
            if (!label || !info) continue;
            const [unit, unitTitle, lecture, lectureTitle] = info;
            for (const [key, title, level] of [
                [unit !== previousUnit ? unit : '', unitTitle, 3],
                [lecture && (unit !== previousUnit || lecture !== previousLecture) ? lecture : '', lectureTitle, 4],
            ]) {
                if (!key) continue;
                const id = `${level}:${input.value}`;
                wanted.add(id);
                let heading = Array.from(root.querySelectorAll('[data-chapter-heading]')).find(e => e.dataset.chapterHeading === id);
                if (!heading) {
                    heading = document.createElement(`h${level}`);
                    heading.dataset.chapterHeading = id;
                    heading.className = 'le-catalog-heading';
                    label.before(heading);
                }
                if (heading.textContent !== title) heading.textContent = title;
            }
            previousUnit = unit;
            previousLecture = lecture;
        }
        root.querySelectorAll('[data-chapter-heading]').forEach(e => {
            if (!wanted.has(e.dataset.chapterHeading)) e.remove();
        });
    };
    update();
    const root = document.getElementById('le-course-catalog');
    if (root) new MutationObserver(update).observe(root, {childList: true, subtree: true, attributes: true, attributeFilter: ['data-chapters', 'value']});
}
