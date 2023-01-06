Comment Spam Filter
===================

There's a simple
`Naive Bayes-based <https://en.wikipedia.org/wiki/Naive_Bayes_classifier>`_
spam filter for comments built in. It's not very smart, but it's good
enough to filter out most spam. It's also very easy to train and very fast
to run. And it's only slightly above one hundred lines of pure Python code.

A comment is considered ham if it's public and not removed. All other comments
are considered spam. It's possible to re-train the spam filter via a
`Django Admin <https://docs.djangoproject.com/en/4.1/ref/contrib/admin/>`_
action on the :code:`SpamFilter` model. The precision, recall and F1 performance
indicators are also shown in the admin interface.

.. image:: images/spam_filter_performance.png
  :width: 800
  :alt: Show a spam filter row in the Django admin interface
