Using a CDN (AWS S3 + Cloudfront)
=================================

When using a CDN, s3 with cloudfront for example, there are some settings
to put in your production config which are not really obvious:

.. code-block:: python

   AWS_AUTO_CREATE_BUCKET = True
   AWS_S3_REGION_NAME = 'eu-central-1'  # if your region differs from default
   AWS_S3_SIGNATURE_VERSION = 's3v4'
   AWS_S3_FILE_OVERWRITE = True
   AWS_S3_CUSTOM_DOMAIN = env('CLOUDFRONT_DOMAIN')

Took me some time to figure out these settings. Those are additional settings,
assumed you already used the django-cookiecutter template.
