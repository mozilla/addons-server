
from south.db import db
from django.db import models
from users.models import *

class Migration:
    
    def forwards(self, orm):
        
        # Adding model 'UserProfile'
        db.create_table('users', (
            ('id', orm['users.UserProfile:id']),
            ('created', orm['users.UserProfile:created']),
            ('modified', orm['users.UserProfile:modified']),
            ('email', orm['users.UserProfile:email']),
            ('firstname', orm['users.UserProfile:firstname']),
            ('lastname', orm['users.UserProfile:lastname']),
            ('password', orm['users.UserProfile:password']),
            ('nickname', orm['users.UserProfile:nickname']),
            ('bio', orm['users.UserProfile:bio']),
            ('emailhidden', orm['users.UserProfile:emailhidden']),
            ('sandboxshown', orm['users.UserProfile:sandboxshown']),
            ('homepage', orm['users.UserProfile:homepage']),
            ('display_collections', orm['users.UserProfile:display_collections']),
            ('display_collections_fav', orm['users.UserProfile:display_collections_fav']),
            ('confirmationcode', orm['users.UserProfile:confirmationcode']),
            ('resetcode', orm['users.UserProfile:resetcode']),
            ('resetcode_expires', orm['users.UserProfile:resetcode_expires']),
            ('notifycompat', orm['users.UserProfile:notifycompat']),
            ('notifyevents', orm['users.UserProfile:notifyevents']),
            ('deleted', orm['users.UserProfile:deleted']),
            ('notes', orm['users.UserProfile:notes']),
            ('location', orm['users.UserProfile:location']),
            ('occupation', orm['users.UserProfile:occupation']),
            ('picture_type', orm['users.UserProfile:picture_type']),
            ('averagerating', orm['users.UserProfile:averagerating']),
        ))
        db.send_create_signal('users', ['UserProfile'])
        
    
    
    def backwards(self, orm):
        
        # Deleting model 'UserProfile'
        db.delete_table('users')
        
    
    
    models = {
        'translations.translation': {
            'Meta': {'unique_together': "(('id', 'locale'),)", 'db_table': "'translations'"},
            'autoid': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'created': ('django.db.models.fields.DateTimeField', [], {'auto_now_add': 'True', 'blank': 'True'}),
            'id': ('django.db.models.fields.IntegerField', [], {}),
            'locale': ('django.db.models.fields.CharField', [], {'max_length': '10'}),
            'localized_string': ('django.db.models.fields.TextField', [], {}),
            'modified': ('django.db.models.fields.DateTimeField', [], {'auto_now': 'True', 'blank': 'True'})
        },
        'users.userprofile': {
            'Meta': {'db_table': "'users'"},
            'averagerating': ('django.db.models.fields.CharField', [], {'max_length': '765', 'blank': 'True'}),
            'bio': ('TranslatedField', [], {}),
            'confirmationcode': ('django.db.models.fields.CharField', [], {'max_length': '765'}),
            'created': ('django.db.models.fields.DateTimeField', [], {'auto_now_add': 'True', 'blank': 'True'}),
            'deleted': ('django.db.models.fields.IntegerField', [], {'null': 'True', 'blank': 'True'}),
            'display_collections': ('django.db.models.fields.IntegerField', [], {}),
            'display_collections_fav': ('django.db.models.fields.IntegerField', [], {}),
            'email': ('django.db.models.fields.EmailField', [], {'unique': 'True', 'max_length': '75'}),
            'emailhidden': ('django.db.models.fields.IntegerField', [], {}),
            'firstname': ('django.db.models.fields.CharField', [], {'max_length': '255'}),
            'homepage': ('django.db.models.fields.CharField', [], {'max_length': '765', 'blank': 'True'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'lastname': ('django.db.models.fields.CharField', [], {'max_length': '255'}),
            'location': ('django.db.models.fields.CharField', [], {'max_length': '765'}),
            'modified': ('django.db.models.fields.DateTimeField', [], {'auto_now': 'True', 'blank': 'True'}),
            'nickname': ('django.db.models.fields.CharField', [], {'max_length': '765', 'blank': 'True'}),
            'notes': ('django.db.models.fields.TextField', [], {'blank': 'True'}),
            'notifycompat': ('django.db.models.fields.IntegerField', [], {}),
            'notifyevents': ('django.db.models.fields.IntegerField', [], {}),
            'occupation': ('django.db.models.fields.CharField', [], {'max_length': '765'}),
            'password': ('django.db.models.fields.CharField', [], {'max_length': '765'}),
            'picture_type': ('django.db.models.fields.CharField', [], {'max_length': '75'}),
            'resetcode': ('django.db.models.fields.CharField', [], {'max_length': '765'}),
            'resetcode_expires': ('django.db.models.fields.DateTimeField', [], {'default': 'datetime.datetime.now'}),
            'sandboxshown': ('django.db.models.fields.IntegerField', [], {})
        }
    }
    
    complete_apps = ['users']
