import django_filters

from .models import Transaction


class TransactionFilterSet(django_filters.FilterSet):
    date_from = django_filters.DateFilter(method="filter_date_from")
    date_to = django_filters.DateFilter(method="filter_date_to")

    class Meta:
        model = Transaction
        fields = ["institution", "branch", "client", "category", "direction"]

    def filter_date_from(self, queryset, name, value):
        return queryset.filter(created_at__date__gte=value)

    def filter_date_to(self, queryset, name, value):
        return queryset.filter(created_at__date__lte=value)
