from django.core.paginator import Paginator


def page(request, rows, key='page', size=30):
    result = Paginator(rows, size).get_page(request.GET.get(key))
    query = request.GET.copy()
    query.pop(key, None)
    result.query_string = query.urlencode()
    result.page_key = key
    return result
