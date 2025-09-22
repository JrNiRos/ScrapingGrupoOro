document.addEventListener('DOMContentLoaded', () => {
    // Crear elementos del cursor
    const cursor = document.createElement('div');
    const cursor2 = document.createElement('div');
    cursor.classList.add('cursor');
    cursor2.classList.add('cursor2');
    document.body.appendChild(cursor);
    document.body.appendChild(cursor2);

    // Seguimiento del cursor
    document.addEventListener('mousemove', (e) => {
        cursor.style.transform = `translate3d(calc(${e.clientX}px - 10px), calc(${e.clientY}px - 10px), 0)`;
        cursor2.style.transform = `translate3d(calc(${e.clientX}px - 4px), calc(${e.clientY}px - 4px), 0)`;
    });

    // Efecto de clic
    document.addEventListener('click', () => {
        cursor.classList.add('click');
        cursor2.classList.add('click');
        setTimeout(() => {
            cursor.classList.remove('click');
            cursor2.classList.remove('click');
        }, 500);
    });

    // Efecto hover en links y botones
    const links = document.querySelectorAll('a, button, .btn, [role="button"]');
    links.forEach(link => {
        link.addEventListener('mouseover', () => {
            cursor.classList.add('hover');
            cursor2.classList.add('hover');
        });
        link.addEventListener('mouseleave', () => {
            cursor.classList.remove('hover');
            cursor2.classList.remove('hover');
        });
    });

    // Ocultar cursor nativo
    document.body.style.cursor = 'none';
    links.forEach(link => {
        link.style.cursor = 'none';
    });
});