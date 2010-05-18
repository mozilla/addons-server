import jingo
from twitter import search
from config import teams, tags

# Create your views here.
def index(request):
    return HttpResponse('foo')

    tweets = search(tags['all'], lang=request.LANG)

    if (len(tweets) < 15):
        extra = search(tags['all'], 'all')
        tweets.extend(extra)
        
    # we only want 15 tweets
    tweets = tweets[:15]
    
    return jingo.render(request, 'firefoxcup/index.html', {
        'tweets': tweets, 
        'teams': teams})

