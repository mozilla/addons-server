def blank_featured_images(apps, schema_editor):
    PrimaryHero = apps.get_model('hero', 'PrimaryHero')
    for shelf in PrimaryHero.objects.all():
        if shelf.image:
            shelf.image = ''
            shelf.save()
