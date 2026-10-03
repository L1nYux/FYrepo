from django import forms
from django.db.models import Q
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User

from . import permissions as perms
from .models import (ChatMessage, Comment, ExpenseClaim, FinanceEntry, Project, Submission, Task,
                     validate_private_files, Announcement, Experiment, ExperimentTemplate,
                     Competition, PublicProfile, TeamContact)

ACCEPT_ATTR = '.txt,.pdf,.doc,.docx,.xls,.xlsx,.md,.markdown,.py,.ipynb,.js,.ts,.r,.sh,.sql,.json,.yaml,.yml,.toml,.csv,.zip,.png,.jpg,.jpeg,.gif,.webp,.bmp'


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """一次可选择多个附件的文件字段（Django 官方推荐写法）。"""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', MultipleFileInput(attrs={'multiple': True, 'accept': ACCEPT_ATTR}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            files = [single(item, initial) for item in data]
        else:
            files = [single(data, initial)]
        return validate_private_files(files)


class RoleLoginForm(AuthenticationForm):
    """登录表单：先选登录身份，再校验账号是否有这个身份。

    用户名一栏允许填用户名或邮箱；邮箱对应多个账号时要求改用用户名，避免登错人。
    """

    username = forms.CharField(label='用户名或邮箱', max_length=150,
                               widget=forms.TextInput(attrs={'autofocus': True, 'autocomplete': 'username'}))
    remember = forms.BooleanField(label='保持登录（30天）',required=False,initial=True)

    def clean_username(self):
        value = (self.cleaned_data.get('username') or '').strip()
        if User.objects.filter(username__iexact=value).exists():
            return value
        matches = list(User.objects.filter(email__iexact=value).values_list('username', flat=True))
        if len(matches) == 1:
            return matches[0]  # 用邮箱登录：换成真正的用户名再走认证。
        if len(matches) > 1:
            raise forms.ValidationError('该邮箱对应多个账号，请改用用户名登录。')
        return value  # 查不到就原样交给认证，由认证给出统一的失败提示。


def normalise_email(value, exclude_user=None):
    """邮箱统一小写并检查唯一性：重置密码按邮箱找人，同一邮箱只能对应一个账号。

    已有的空邮箱、重复邮箱由迁移 `0010` 处理；这里拦住新的重复。
    """
    email = (value or '').strip().lower()
    if not email:
        raise forms.ValidationError('请填写邮箱：忘记密码时需要用它接收重置链接。')
    clashes = User.objects.filter(email__iexact=email)
    if exclude_user is not None:
        clashes = clashes.exclude(pk=exclude_user.pk)
    if clashes.exists():
        raise forms.ValidationError('该邮箱已被其他账号使用，请换一个。')
    return email


class RegisterForm(UserCreationForm):
    """邀请码注册。邮箱必填且唯一：它是成员忘记密码时唯一的自助找回凭据。"""

    invite_code = forms.CharField(label='邀请码', max_length=100, strip=True)
    email = forms.EmailField(label='邮箱（用于找回密码）', max_length=254)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email')
        labels = {'username': '账户名'}

    def clean_username(self):
        username = super().clean_username()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('账户名已被使用。')
        return username

    def clean_email(self):
        return normalise_email(self.cleaned_data.get('email'))


class ChatMessageForm(forms.ModelForm):
    attachments = MultipleFileField(label='附件', required=False)
    references = forms.JSONField(required=False, initial=list, widget=forms.HiddenInput)

    class Meta:
        model = ChatMessage
        fields = ('body',)
        labels = {'body': ''}
        widgets = {'body': forms.Textarea(attrs={'rows': 2, 'maxlength': 2000,
                                                 'placeholder': '说点什么…（回车发送，Shift+回车换行）'})}

    def __init__(self, *args, **kwargs):
        self.allow_references = kwargs.pop('allow_references', False)
        self.existing_attachments = kwargs.pop('existing_attachments', False)
        super().__init__(*args, **kwargs)
        self.fields['body'].required = False

    def clean_references(self):
        values = self.cleaned_data.get('references') or []
        if not isinstance(values, list) or len(values) > 5:
            raise forms.ValidationError('每条消息最多引用 5 条内容。')
        if values and not self.allow_references:
            raise forms.ValidationError('请在消息中心引用内容。')
        cleaned = []
        for value in values:
            if not isinstance(value, str) or len(value) > 40:
                raise forms.ValidationError('引用格式不正确，请重新选择。')
            kind, separator, pk = value.partition(':')
            if kind not in ('task', 'experiment', 'entry', 'claim', 'announcement') or separator != ':' or not pk.isascii() or not pk.isdigit() or int(pk) <= 0:
                raise forms.ValidationError('引用格式不正确，请重新选择。')
            value = f'{kind}:{int(pk)}'
            if value not in cleaned:
                if int(pk) > 9223372036854775807:
                    raise forms.ValidationError('引用格式不正确，请重新选择。')
                cleaned.append(value)
        return cleaned

    def clean(self):
        data = super().clean()
        if not data.get('body', '').strip() and not data.get('attachments') and not data.get('references') and not self.existing_attachments:
            raise forms.ValidationError('请输入消息、添加附件或引用内容。')
        return data


class ProfileForm(forms.ModelForm):
    """个人中心里由本人维护的资料：姓名与邮箱。

    邮箱必填且唯一：它既是登录名之一，也是忘记密码时接收重置链接的地址。
    """

    class Meta:
        model = User
        fields = ('first_name', 'email')
        labels = {'first_name': '姓名（可选）', 'email': '邮箱（用于找回密码）'}
        widgets = {'email': forms.EmailInput(attrs={'autocomplete': 'email'})}

    def clean_email(self):
        return normalise_email(self.cleaned_data.get('email'), exclude_user=self.instance)


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ('name', 'goal', 'description', 'owner', 'members', 'budget', 'public_summary')
        labels = {'name': '项目名称', 'goal': '项目目标', 'description': '项目说明（可选）',
                  'owner': '项目负责人', 'members': '项目成员', 'budget': '项目预算（元，可选）'}
        widgets = {'goal': forms.Textarea(attrs={'rows': 3}),
                   'description': forms.Textarea(attrs={'rows': 3}),
                   'members': forms.CheckboxSelectMultiple()}

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.fields['owner'].queryset = User.objects.filter(is_active=True).order_by('username')
        self.fields['members'].queryset = User.objects.filter(is_active=True, is_staff=False).order_by('username')
        self.fields['members'].required = False
        self.fields['owner'].required = False
        self.fields['name'].widget.attrs.update(placeholder='一句话说明项目名称', autofocus=True)
        if not self.instance.pk and self.user:
            self.fields['owner'].initial = self.user.pk

    def clean_owner(self):
        return self.cleaned_data.get('owner') or (self.instance.owner if self.instance.pk else self.user)

    def save(self, commit=True):
        project = super().save(commit=commit)
        if commit:
            project.members.remove(project.owner)  # 负责人不必重复出现在成员列表里。
        return project


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ('title', 'description', 'assignee', 'members', 'due_date', 'category', 'competition')
        labels = {'title': '任务名称', 'description': '任务说明', 'assignee': '任务负责人', 'due_date': '截止日期'}
        widgets = {'description': forms.Textarea(attrs={'rows': 5}),
                   'due_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'})}

    def __init__(self, *args, project=None, parent=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project or getattr(self.instance, 'project', None)
        self.fields['members'].widget = forms.CheckboxSelectMultiple()
        self.parent = parent if parent is not None else getattr(self.instance, 'parent', None)
        if self.project is not None:
            self.fields['assignee'].queryset = User.objects.filter(
                pk__in=self.project.participant_ids, is_active=True).order_by('username')
        else:
            self.fields['assignee'].queryset = User.objects.filter(is_active=True, is_staff=False).order_by('username')

        self.fields['members'].queryset = self.fields['assignee'].queryset
        self.fields['competition'].queryset = Competition.objects.filter(
            Q(archived_at__isnull=True) | Q(pk=self.instance.competition_id))
        self.fields['competition'].empty_label = '不关联比赛'
        self.fields['category'].required = False
        self.fields['assignee'].required = False
        self.default_assignee = self.instance.assignee if self.instance.pk else (
            user if user and self.project and user.pk in self.project.participant_ids else self.project.owner if self.project else user)
        if not self.instance.pk and self.default_assignee:
            self.fields['assignee'].initial = self.default_assignee.pk
        self.fields['title'].widget.attrs.update(placeholder='一句话写清要做什么', autofocus=True)
        self.fields['description'].widget.attrs.update(rows=3, placeholder='需要时再补充说明')

    def clean_assignee(self):
        return self.cleaned_data.get('assignee') or self.default_assignee

    def clean_category(self):
        return self.cleaned_data.get('category') or 'other'

    def save(self, commit=True):
        task = super().save(commit=False)
        if self.project is not None:
            task.project = self.project
        if self.parent is not None:
            task.parent = self.parent
        if commit:
            task.save()
            self.save_m2m()
        return task


class ProgressForm(forms.Form):
    progress = forms.IntegerField(label='完成进度（0-99）', min_value=0, max_value=99)


class SubmissionForm(forms.ModelForm):
    attachments = MultipleFileField(label='附件（可选，可多选）', required=False,
                                    help_text='支持文档、图片、源码、CSV 和 ZIP；单个 20 MB，最多 5 个，总计 40 MB。请勿上传 API 密钥。')

    class Meta:
        model = Submission
        fields = ('summary', 'source_url', 'experiments')
        labels = {'summary': '成果内容（可直接写文字，不必上传附件）'}
        widgets = {'summary': forms.Textarea(attrs={'rows': 6})}

    finish = forms.BooleanField(label='提交后结项或申请审核', required=False, initial=False)

    def __init__(self, *args, **kwargs):
        project = kwargs.pop('project', None)
        task = kwargs.pop('task', None)
        self.inline_experiment = kwargs.pop('inline_experiment', False)
        super().__init__(*args, **kwargs)
        if not task and not self.instance.task_id:
            self.fields.pop('finish')
        if project:
            self.fields['experiments'].queryset = Experiment.objects.filter(Q(project=project) | Q(project__isnull=True))
        self.fields['experiments'].widget = forms.CheckboxSelectMultiple(choices=self.fields['experiments'].choices)
        self.fields['experiments'].label_from_instance = lambda obj: f'{obj.number} · {obj.title}'
        self.fields['summary'].widget.attrs.update(rows=3, placeholder='写一句话，或直接添加成果文件…')

    def clean(self):
        data = super().clean()
        if not self.inline_experiment and not any((data.get('summary', '').strip(), data.get('source_url'), data.get('experiments'), data.get('attachments'))):
            raise forms.ValidationError('请填写文字、添加附件、链接或实验记录中的至少一项。')
        return data


class CommentForm(forms.ModelForm):
    attachments = MultipleFileField(label='附件（可选，可多选）', required=False)

    class Meta:
        model = Comment
        fields = ('kind', 'body')
        labels = {'kind': '类型', 'body': '内容'}
        widgets = {'body': forms.Textarea(attrs={'rows': 3, 'placeholder': '目标、思路、问题或结论…'})}


class ReviewForm(forms.Form):
    decision = forms.ChoiceField(label='审核决定', choices=[('accept', '通过'), ('reject', '退回修改')])
    note = forms.CharField(label='审核结论', max_length=3000, required=False, widget=forms.Textarea(attrs={'rows': 3}))

    def clean(self):
        data = super().clean()
        if data.get('decision') == 'reject' and not (data.get('note') or '').strip():
            self.add_error('note', '退回时请填写原因。')
        return data


class FinalForm(forms.Form):
    note = forms.CharField(label='选用说明（可选）', max_length=1000, required=False,
                           widget=forms.Textarea(attrs={'rows': 2}))


class FinanceForm(forms.ModelForm):
    attachments = MultipleFileField(label='凭证（可选，可多选）', required=False)

    class Meta:
        model = FinanceEntry
        fields = ('kind', 'amount', 'occurred_on', 'project', 'memo')
        labels = {'kind': '类型', 'amount': '金额（元）', 'occurred_on': '发生日期', 'memo': '说明',
                  'project': '关联项目（可选）'}
        widgets = {'occurred_on': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
                   'memo': forms.Textarea(attrs={'rows': 4})}

    def __init__(self, *args, **kwargs):
        from django.utils import timezone
        super().__init__(*args, **kwargs)
        self.fields['project'].queryset = Project.objects.filter(archived_at__isnull=True).order_by('name')
        self.fields['project'].required = False
        self.fields['project'].empty_label = '不关联项目'
        self.fields['occurred_on'].required = False
        if not self.instance.pk:
            self.fields['occurred_on'].initial = timezone.localdate()
            self.fields['kind'].initial = 'expense'
        self.fields['memo'].widget.attrs.update(rows=2, placeholder='一句话说明用途')

    def clean_occurred_on(self):
        from django.utils import timezone
        return self.cleaned_data.get('occurred_on') or timezone.localdate()


class ClaimForm(forms.ModelForm):
    attachments = MultipleFileField(label='发票等凭证（可选，可多选）', required=False)

    class Meta:
        model = ExpenseClaim
        fields = ('amount', 'occurred_on', 'project', 'memo')
        labels = {'amount': '申请金额（元）', 'occurred_on': '发生日期', 'memo': '事由',
                  'project': '关联项目（可选）'}
        widgets = {'occurred_on': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
                   'memo': forms.Textarea(attrs={'rows': 4})}

    def __init__(self, *args, user=None, **kwargs):
        """项目下拉框只列出申请人参与的项目；管理员可以看到全部未归档项目。

        项目可以不选（下拉框第一项「不关联项目」），表示与具体项目无关的团队公共开支。
        """
        super().__init__(*args, **kwargs)
        projects = Project.objects.filter(archived_at__isnull=True)
        if user is not None and not user.is_staff:
            projects = projects.filter(Q(owner=user) | Q(members=user)).distinct()
        self.fields['project'].queryset = projects.order_by('name')
        self.fields['project'].required = False
        self.fields['project'].empty_label = '不关联项目'

        from django.utils import timezone
        self.fields['occurred_on'].required = False
        self.fields['occurred_on'].initial = timezone.localdate()
        self.fields['memo'].widget.attrs.update(rows=2, placeholder='这笔钱用于什么')

    def clean_occurred_on(self):
        from django.utils import timezone
        return self.cleaned_data.get('occurred_on') or timezone.localdate()


class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ('title', 'body', 'is_published')
        widgets = {'body': forms.Textarea(attrs={'rows': 6})}


class ExperimentForm(forms.ModelForm):
    attachments = MultipleFileField(label='实验附件', required=False)
    template_name = forms.CharField(label='将参数另存为模板', max_length=100, required=False)

    class Meta:
        model = Experiment
        fields = ('number', 'title', 'content', 'purpose', 'project', 'conclusion', 'source_id', 'batch', 'model_name',
                  'prompt_version', 'procedure', 'result', 'human_review', 'github_url', 'git_ref')
        labels = {'github_url': '源码 / 材料链接', 'git_ref': '版本标识（可选）'}
        widgets = {'content': forms.Textarea(attrs={'rows': 4, 'placeholder': '一句话也可以；已有 Word、Excel、PDF 可直接上传。'}),
                   'purpose': forms.Textarea(attrs={'rows': 2}),
                   'procedure': forms.Textarea(attrs={'rows': 3}),
                   'result': forms.Textarea(attrs={'rows': 3}),
                   'conclusion': forms.Textarea(attrs={'rows': 2}),
                   'human_review': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user')
        self.user = user
        super().__init__(*args, **kwargs)
        projects = Project.objects.filter(archived_at__isnull=True)
        if not user.is_staff:
            projects = projects.filter(Q(owner=user) | Q(members=user)).distinct()
        self.fields['project'].queryset = projects
        self.fields['project'].help_text = '可选；任务提交时直接引用这里的记录。'
        self.fields['number'].required = False
        self.fields['number'].help_text = '留空自动生成。'
        self.fields['title'].required = False
        self.fields['title'].label = '名称（可选）'
        self.fields['title'].widget.attrs['placeholder'] = '不填则使用文件名或正文第一行'
        if self.instance.pk and (self.instance.origin_task_id or self.instance.submissions.exists()):
            self.fields['project'].disabled = True

    @property
    def parameter_rows(self):
        if self.is_bound:
            names = self.data.getlist(self.add_prefix('parameter_name'))
            values = self.data.getlist(self.add_prefix('parameter_value'))
            rows = [{'name': name, 'value': values[i] if i < len(values) else ''}
                    for i, name in enumerate(names)]
        else:
            rows = list(self.instance.parameters or [])
        return rows or [{'name': '', 'value': ''}]

    def clean(self):
        data = super().clean()
        if not data.get('title'):
            from pathlib import Path
            files = data.get('attachments') or []
            text = (data.get('content') or '').strip()
            if files:
                data['title'] = Path(files[0].name).stem[:160]
            elif text:
                data['title'] = text.splitlines()[0][:160]
            elif self.instance.pk:
                data['title'] = self.instance.title
            else:
                self.add_error('title', '上传一个文件，或写一句记录内容即可保存。')
        names = self.data.getlist(self.add_prefix('parameter_name'))
        values = self.data.getlist(self.add_prefix('parameter_value'))
        if len(names) > 40 or len(names) != len(values):
            raise forms.ValidationError('参数最多 40 项，请填写完整的参数名和值。')
        rows, seen = [], set()
        for name, value in zip(names, values):
            name, value = name.strip(), value.strip()
            if not name and not value:
                continue
            if not name or len(name) > 80 or len(value) > 2000 or name in seen:
                raise forms.ValidationError('参数名须唯一且不超过 80 字，值不超过 2000 字。')
            seen.add(name)
            rows.append({'name': name, 'value': value})
        data['parameters'] = rows
        return data

    def save_record(self, origin_task=None):
        import uuid
        from .models import attach_files
        item = self.save(commit=False)
        if not item.number:
            item.number = 'EXP-' + uuid.uuid4().hex[:12].upper()
        if not item.pk:
            item.created_by = self.user
        if origin_task:
            item.origin_task = origin_task
            item.project = origin_task.project
        if item.pk and item.visibility == 'public':
            item.visibility = 'pending'
        item.parameters = self.cleaned_data['parameters']
        item.save()
        attach_files('experiment', item, self.cleaned_data.get('attachments', []), self.user)
        if self.cleaned_data.get('template_name'):
            ExperimentTemplate.objects.update_or_create(name=self.cleaned_data['template_name'],
                created_by=self.user, defaults={'parameters': item.parameters})
        return item


class CompetitionForm(forms.ModelForm):
    class Meta:
        model = Competition
        fields = ('name', 'owner', 'deadline', 'website', 'description')
        widgets = {'deadline': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
                   'description': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['owner'].queryset = User.objects.filter(is_active=True).exclude(
            member_profile__tier='normal').order_by('username')


class PublicProfileForm(forms.ModelForm):
    class Meta:
        model = PublicProfile
        fields = ('display_name', 'research_area', 'bio', 'github_url', 'is_public')
        widgets = {'bio': forms.Textarea(attrs={'rows': 5})}

    def clean(self):
        data = super().clean()
        if data.get('is_public') and not data.get('display_name', '').strip():
            self.add_error('display_name', '展示成员资料前请填写公开姓名。')
        return data


class TeamContactForm(forms.ModelForm):
    class Meta:
        model = TeamContact
        fields = ('email', 'phone', 'github_url', 'other', 'description')
        widgets = {'other': forms.Textarea(attrs={'rows': 3}), 'description': forms.Textarea(attrs={'rows': 4})}
