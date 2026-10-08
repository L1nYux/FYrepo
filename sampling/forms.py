from django import forms
from core import permissions as perms
from core.models import Project
from .models import SamplingRun
from .scope import JOURNALS, PERIOD_MAP, REGISTRY


def accessible_projects(viewer):
    qs = Project.objects.filter(archived_at__isnull=True).order_by('name')
    return qs if viewer is not None and perms.is_team_member(viewer) else qs.none()


class SamplingRunForm(forms.ModelForm):
    # 使用模型字段名；clean_periods 在 ModelForm._post_clean 之前转换到规范 JSON。
    periods = forms.MultipleChoiceField(label='研究时期', choices=[(p['id'], p['label']) for p in PERIOD_MAP.values()],
                                        widget=forms.CheckboxSelectMultiple, error_messages={'required': '请至少选择一个研究时期'})
    selected_tiers = forms.MultipleChoiceField(label='期刊层级', choices=[(t, t) for t in REGISTRY['tiers']],
                                               widget=forms.CheckboxSelectMultiple, error_messages={'required': '请至少选择一个期刊层级'})
    selected_journals = forms.MultipleChoiceField(label='具体期刊', choices=[(j, j) for j in JOURNALS],
                                                  widget=forms.CheckboxSelectMultiple, error_messages={'required': '请至少选择一本期刊'})
    main_n = forms.IntegerField(label='每格主样本数', min_value=1, max_value=32767, initial=1)
    reserve_n = forms.IntegerField(label='每格备用样本数', min_value=0, max_value=32767, initial=1)
    holdout_n = forms.IntegerField(label='每格留出样本数', min_value=1, max_value=32767, initial=1, required=False)
    holdout_start = forms.IntegerField(label='留出开始年份', min_value=1900, max_value=2100, required=False)
    holdout_end = forms.IntegerField(label='留出结束年份', min_value=1900, max_value=2100, required=False)

    class Meta:
        model = SamplingRun
        fields = ['name', 'project', 'version', 'periods', 'selected_tiers', 'selected_journals',
                  'main_n', 'reserve_n', 'holdout_enabled', 'holdout_n', 'holdout_start', 'holdout_end',
                  'sampling_method', 'sampling_seed']
        widgets = {'name': forms.TextInput(attrs={'placeholder': '请输入样本集名称'}),
                   'version': forms.TextInput(attrs={'placeholder': '例如：v1'})}
        error_messages = {'name': {'required': '请输入样本集名称'}}

    def __init__(self, *args, user=None, viewer=None, **kwargs):
        # 兼容 v1 旧 POST 的字段名，输出一律采用正式模型字段名。
        if args and args[0] is not None:
            data = args[0].copy()
            for old, new in [('period_ids', 'periods'), ('tier_ids', 'selected_tiers'), ('journal_names', 'selected_journals')]:
                if old in data and new not in data:
                    if hasattr(data, 'setlist'):
                        data.setlist(new, data.getlist(old))
                    else:
                        data[new] = data[old]
            args = (data, *args[1:])
        super().__init__(*args, **kwargs)
        self.fields['project'].queryset = accessible_projects(viewer or user)
        self.fields['project'].required = False
        self.fields['project'].empty_label = '不关联项目'
        self.fields['project'].label = '关联项目'
        self.fields['project'].error_messages['invalid_choice'] = '项目不存在、已归档或当前身份无权访问'
        if self.instance.pk:
            self.initial['periods'] = [p['id'] for p in self.instance.periods]
        enabled = self.fields['holdout_enabled'].widget.value_from_datadict(self.data, self.files, self.add_prefix('holdout_enabled')) if self.is_bound else self.initial.get('holdout_enabled', False)
        for name in ('holdout_n', 'holdout_start', 'holdout_end'):
            self.fields[name].required = bool(enabled)
            if not enabled:
                self.fields[name].disabled = True
                self.initial[name] = 1 if name == 'holdout_n' else None
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.NumberInput):
                field.widget.attrs.update(min=field.min_value, max=field.max_value)
            field.widget.attrs['aria-describedby'] = f'id_{name}_errors'
            if field.required:
                field.widget.attrs['data-required'] = 'true'

    def clean_periods(self):
        # 按 registry 顺序保存，避免用户 POST 顺序改变抽样格编号。
        selected = set(self.cleaned_data['periods'])
        return [dict(p) for pid, p in PERIOD_MAP.items() if pid in selected]

    def clean_selected_tiers(self):
        return [t for t in REGISTRY['tiers'] if t in self.cleaned_data['selected_tiers']]

    def clean_selected_journals(self):
        return [j for j in JOURNALS if j in self.cleaned_data['selected_journals']]

    def clean(self):
        data = super().clean()
        if not data.get('holdout_enabled'):
            data.update(holdout_n=1, holdout_start=None, holdout_end=None)
        return data


class CandidateUploadForm(forms.Form):
    file = forms.FileField(label='题录文件', widget=forms.FileInput(attrs={'accept': '.csv,.json,.xlsx,.xlsm,.xls'}),
                           help_text='支持 CSV、JSON、XLSX/XLSM、知网 HTML-XLS；上限 20 MB。')

    def clean_file(self):
        file = self.cleaned_data['file']
        if file.size > 20 * 1024 * 1024:
            raise forms.ValidationError('题录文件不能超过 20 MB')
        return file


class ResultBundleImportForm(forms.Form):
    project = forms.ModelChoiceField(label='关联项目', queryset=Project.objects.none(), required=False, empty_label='不关联项目')
    file = forms.FileField(label='抽样结果包', widget=forms.FileInput(attrs={'accept': '.zip'}))
    name = forms.CharField(label='样本集名称', max_length=160, required=False)
    version = forms.CharField(label='版本', max_length=40, initial='imported')

    def __init__(self, *args, user=None, viewer=None, **kwargs):
        kwargs.setdefault('auto_id', 'bundle_%s')
        super().__init__(*args, **kwargs)
        self.fields['project'].queryset = accessible_projects(viewer or user)

    def clean_file(self):
        file = self.cleaned_data['file']
        if file.size > 40 * 1024 * 1024:
            raise forms.ValidationError('结果包不能超过 40 MB')
        return file
