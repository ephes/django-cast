############
Installation
############

.. note::
   This page has been reorganized. Please see:

   - :doc:`quickstart` - For creating new django-cast projects (recommended)
   - :doc:`integrate` - For adding django-cast to existing Django projects

Choose Your Path
================

New Project
-----------

If you're starting a fresh project, use the **quickstart** command that sets everything up automatically:

.. code-block:: shell

    mkdir myproject
    cd myproject
    uv venv
    uv pip install django-cast
    uv run django-cast-quickstart mysite

See :doc:`quickstart` for the complete guide.

Existing Project
----------------

If you have an existing Django project and want to add blogging/podcasting features:

See :doc:`integrate` for step-by-step integration instructions.
