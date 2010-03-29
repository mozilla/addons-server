import jingo


def about_amo(request):
    """'About Mozilla Add-ons' Page"""
    return jingo.render(request, 'pages/about.lhtml')


def faq(request):
    """Frequently Asked Questions"""
    return jingo.render(request, 'pages/faq.lhtml')
