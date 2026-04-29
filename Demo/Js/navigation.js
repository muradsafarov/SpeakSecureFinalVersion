/* ===========================================================
   SpeakSecure - Navigation
   Handles page transitions (home, enrol, verify, settings, delete)
   and the expandable settings dropdown.
   =========================================================== */

/**
 * Navigate to a page with fade transition.
 * Fades out current page, switches content, fades in new page.
 */
function navigateTo(page) {
    const allPages = document.querySelectorAll('.page');

    // Fade out current page
    allPages.forEach(p => {
        if (p.classList.contains('active')) {
            p.style.opacity = '0';
            p.style.transform = 'translateY(-10px)';
        }
    });

    // After fade-out, switch pages and fade in the new one
    setTimeout(() => {
        allPages.forEach(p => {
            p.classList.remove('active');
            p.style.opacity = '';
            p.style.transform = '';
        });
        const target = document.getElementById('page-' + page);
        target.classList.add('active');

        // If navigating to verify/enrol while NOT signed in,
        // make sure we start with a clean form.
        // This handles cases like: delete account → home → sign in.
        if ((page === 'verify' || page === 'enrol') && typeof getCurrentUser === 'function' && !getCurrentUser()) {
            if (typeof resetAllForms === 'function') {
                resetAllForms();
            }
        }

        // Trigger fade-in animation on next frame
        requestAnimationFrame(() => {
            target.style.opacity = '1';
            target.style.transform = 'translateY(0)';
        });

        // Smooth scroll to top after page change
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }, 300);
}