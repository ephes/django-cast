import json
import pytz  # noqa - will get used soon
import logging

from datetime import datetime, timedelta  # noqa - will get used soon

from django.db.models import Count
from django.views.generic import TemplateView
from django.db.models.functions import TruncWeek
from django.contrib.auth.mixins import LoginRequiredMixin

import plotly.graph_objs as go
from plotly.utils import PlotlyJSONEncoder

from .models import Request

logger = logging.getLogger(__name__)


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "cast/dashboard.html"

    def get_day_chart(self):
        qs = (
            Request.objects.extra(select={"day": "date(timestamp)"})
            .values("day")
            .annotate(hits=Count("pk"))
        )
        x, y = [], []
        for num, row in enumerate(qs, 1):
            # trace["x"].append(num)
            x.append(row["day"].strftime("%Y-%m-%d"))
            y.append(row["hits"])
        trace = go.Scatter(x=x, y=y, text="Hits", name="Hits per day")

        layout = go.Layout(
            title=go.layout.Title(text="Hits per day", xref="paper", x=0),
            xaxis=go.layout.XAxis(title=go.layout.xaxis.Title(text="Days")),
            yaxis=go.layout.YAxis(title=go.layout.yaxis.Title(text="Hits")),
        )
        return trace, layout

    def last_day(self, d, day_name):
        days_of_week = [
            "sunday",
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
        ]
        target_day = days_of_week.index(day_name.lower())
        delta_day = target_day - d.isoweekday()
        if delta_day >= 0:
            delta_day -= 7  # go back 7 days
        return d + timedelta(days=delta_day)

    def get_week_chart(self):
        # last_sunday = self.last_day(pytz.utc.localize(datetime.today()), 'sunday')
        qs = (
            Request.objects
            # .filter(timestamp__lte=last_sunday)
            .annotate(week=TruncWeek("timestamp"))
            .values("week")
            .annotate(hits=Count("pk"))
        )
        x, y = [], []
        for num, row in enumerate(qs, 1):
            # trace["x"].append(num)
            x.append(row["week"].strftime("%Y-%m-%d"))
            y.append(row["hits"])
        trace = go.Scatter(x=x, y=y, text="Hits")

        layout = go.Layout(
            title=go.layout.Title(text="Hits per week", xref="paper", x=0),
            xaxis=go.layout.XAxis(title=go.layout.xaxis.Title(text="Weeks")),
            yaxis=go.layout.YAxis(title=go.layout.yaxis.Title(text="Hits")),
        )
        return trace, layout

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # data/layout for hits per day chart
        day_trace, day_layout = self.get_day_chart()
        day_data = [day_trace]
        context["day_data"] = json.dumps(day_data, cls=PlotlyJSONEncoder)
        context["day_layout"] = json.dumps(day_layout, cls=PlotlyJSONEncoder)

        # data/layout for hits per week chart
        week_trace, week_layout = self.get_week_chart()
        week_data = [week_trace]
        context["week_data"] = json.dumps(week_data, cls=PlotlyJSONEncoder)
        context["week_layout"] = json.dumps(week_layout, cls=PlotlyJSONEncoder)
        return context
