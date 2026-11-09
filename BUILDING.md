# Source and installer build

Clone Local Suite and ContourLab source alongside this repository, or set LOCAL_SUITE_SOURCE and CONTOURLAB_SOURCE to their source folders. The tests reuse the host dependencies; they do not install or run real model weights.

Run `python tests/test_lung_plugin.py` and `python tests/test_installer_driver.py`. For browser checks, start `python tests/ui_server.py` and then `python tests/test_browser.py` in a separate terminal with Playwright available.

The release build is coordinated with Local Suite. Freeze plugin code with `python build/build_setup.py freeze <new-folder> --host-sdk <suite-source>/app/radai_lung_install.py`. Build the lightweight Suite SETUP after this pin is recorded. Then run `python build/build_setup.py setup <frozen-folder> <suite-setup.zip> <suite-source>/app/radai_lung_install.py <output-folder>`.

Only the two lightweight SETUP ZIP files are release assets. Python, model weights and optional reporting resources are downloaded after acceptance on the installation machine. No clinical data or test captures are included.
